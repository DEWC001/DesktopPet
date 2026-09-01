"""摸头互动冒烟测试（offscreen 真实构造 PetWindow）。

覆盖 1.4.0 改动里「只有跑起来才暴露」的逻辑：
  - 像素级命中检测（精灵图四周透明区不能算摸到身体）
  - 进入 / 离开身体的状态切换
  - 抚摸距离累计 → 记一次抚摸 → 达到阈值触发大反应
  - 静默（免打扰/专注）时不弹跳、离开（锁屏）时完全不响应
  - 弹动动画不叠加（否则窗口会卡在半空）
  - 台词冷却与提醒气泡不被抢

运行：
    QT_QPA_PLATFORM=offscreen python scripts/test_pet_interaction.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

PASS = 0
FAIL = 0

BODY_BOX = (20, 20, 80, 80)  # 合成图里的不透明区域（120x120 画布）


def check(name: str, fn):
    global PASS, FAIL
    try:
        fn()
        PASS += 1
        print(f"  PASS  {name}")
    except Exception as exc:  # noqa: BLE001
        FAIL += 1
        print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()


def assert_true(cond, msg="断言失败"):
    if not cond:
        raise AssertionError(msg)


def make_body_pixmap(box=BODY_BOX, size=120, opaque=True):
    """合成一张「中间一块不透明、四周透明」的假精灵图。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    if opaque:
        p = QPainter(pm)
        p.fillRect(box[0], box[1], box[2], box[3], QColor(0, 0, 0, 255))
        p.end()
    return pm


def install_body(window, box=BODY_BOX, name="idle", opaque=True):
    """替换某一帧为合成图并刷新缓存，让命中检测可控。"""
    window.frames[name] = make_body_pixmap(box, opaque=opaque)
    window._alpha_cache.clear()
    window._rebuild_breath_cache()
    window._on_breath()  # 让 label 真正贴上这一帧
    return window.frames[name]


def point_at(window, fx: float, fy: float) -> QPoint:
    """按相对比例算出窗口坐标（自动算上 label 偏移与呼吸缩放）。"""
    pm = window.label.pixmap()
    assert_true(pm is not None and not pm.isNull(), "label 上应有 pixmap")
    return QPoint(
        int(window.label.x() + pm.width() * fx),
        int(window.label.y() + pm.height() * fy),
    )


def reset_pet(window) -> None:
    window._hovering = False
    window._pet_bouncing = False
    window._pet_anim = None
    window._pet_strokes = 0
    window._pet_move_accum = 0.0
    window._pet_last_pos = None
    window._last_pet_quote_at = 0.0
    window._override_frame = None
    window._override_until = 0
    window._cancel_pending_jumps()


def main() -> int:
    from pet import config
    from pet.brain import PetBrain
    from pet.window import PetWindow

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    window = PetWindow()
    window.show()
    window.brain.state = PetBrain.IDLE

    # 统计弹动与跳跃
    calls = {"bounce": 0, "jump": 0, "quote": 0}
    orig_bounce, orig_jump, orig_say = window._pet_bounce, window._do_jump, window._say

    def counting_bounce():
        calls["bounce"] += 1
        orig_bounce()

    def counting_jump(dx=None):
        calls["jump"] += 1
        orig_jump(dx)

    def counting_say(messages):
        calls["quote"] += 1
        orig_say(messages)

    window._pet_bounce = counting_bounce
    window._do_jump = counting_jump
    window._say = counting_say

    print("[1] 像素级命中检测")

    def t_hit_center():
        install_body(window)
        reset_pet(window)
        assert_true(window._hit_body(point_at(window, 0.5, 0.5)), "身体中心应命中")

    check("身体中心命中", t_hit_center)

    def t_miss_corner():
        install_body(window)
        assert_true(not window._hit_body(point_at(window, 0.02, 0.02)), "透明角落不应命中")

    check("透明角落不命中", t_miss_corner)

    def t_miss_transparent_frame():
        install_body(window, opaque=False)
        assert_true(not window._hit_body(point_at(window, 0.5, 0.5)), "全透明帧不命中")

    check("全透明帧不命中", t_miss_transparent_frame)

    def t_miss_outside():
        install_body(window)
        assert_true(not window._hit_body(QPoint(-5, -5)), "窗口外坐标不命中")
        assert_true(
            not window._hit_body(QPoint(window.width() + 50, window.height() + 50)),
            "超出右下角不命中",
        )

    check("越界坐标不命中", t_miss_outside)

    def t_hit_fixed_to_idle():
        """命中必须固定按 idle 帧算，否则换帧会把光标「抖出」身体。

        实测 feidudu 皮肤 idle 与 laugh 的轮廓只有 79% 重合——摸头会临时切到
        laugh 帧，跟着当前帧走就会中断互动（默认皮肤两帧完全相同，测不出来）。
        """
        install_body(window, name="idle", box=BODY_BOX)
        install_body(window, name="laugh", box=(0, 0, 40, 40))  # 轮廓完全不同
        window._override_frame = "laugh"
        window._override_until = time.time() * 1000 + 5000
        window._on_breath()
        try:
            assert_true(window._current_frame_name() == "laugh", "当前帧应为 laugh")
            assert_true(
                window._hit_body(point_at(window, 0.5, 0.5)),
                "切到笑帧后仍应按 idle 轮廓命中（否则互动会中断）",
            )
        finally:
            window._override_frame = None
            window._override_until = 0
            window._on_breath()

    check("命中固定按 idle 轮廓（换帧不掉光标）", t_hit_fixed_to_idle)

    def t_alpha_cache_cleared():
        install_body(window)
        assert_true(
            "idle" in window._alpha_cache or window._alpha_cache.get("idle") is None,
            "alpha 缓存可为空",
        )
        window._hit_body(point_at(window, 0.5, 0.5))
        assert_true("idle" in window._alpha_cache, "命中一次后应缓存 alpha 图")
        window._load_all_frames()
        assert_true(window._alpha_cache == {}, "重新加载帧后必须清空 alpha 缓存")

    check("换肤/改大小时 alpha 缓存失效", t_alpha_cache_cleared)

    print("[2] 进入 / 离开身体")

    def t_enter_body():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        calls["bounce"] = 0
        window._update_pet(point_at(window, 0.5, 0.5))
        assert_true(window._hovering, "落到身上应进入互动态")
        # 落地**不弹跳**：蹦一下会跟「双击跳」的反馈撞车，用户会以为自己点到了
        assert_true(calls["bounce"] == 0, f"落地不应弹跳，实际 {calls['bounce']}")
        assert_true(
            window._override_frame == "laugh", "有 laugh 帧时应切到笑帧"
        )

    check("鼠标落到身上触发互动（只切表情，不弹跳）", t_enter_body)

    def t_enter_then_stroke_bounces():
        """落地不跳、动起来摸才跳——两个动作必须有区别。"""
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        calls["bounce"] = 0
        # 两个点都要落在 body box（20~80）内，否则会掉出身体退出互动态
        window._update_pet(point_at(window, 0.25, 0.5))  # 落地
        assert_true(calls["bounce"] == 0, "落地阶段不应弹跳")
        window._update_pet(point_at(window, 0.75, 0.5))  # 横移 60px+ → 记一次抚摸
        assert_true(calls["bounce"] == 1, f"抚摸一下应弹跳，实际 {calls['bounce']}")

    check("落地不跳 / 抚摸才跳（与双击反馈区分）", t_enter_then_stroke_bounces)

    def t_enter_miss_noop():
        install_body(window)
        reset_pet(window)
        calls["bounce"] = 0
        window._update_pet(point_at(window, 0.02, 0.02))
        assert_true(not window._hovering, "透明区不应进入互动态")
        assert_true(calls["bounce"] == 0, "未摸到身体不应有反馈")

    check("透明区不触发互动", t_enter_miss_noop)

    def t_wake_on_pet():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.SLEEP
        window._update_pet(point_at(window, 0.5, 0.5))
        assert_true(
            window.brain.state != PetBrain.SLEEP,
            f"睡觉时被摸应醒来，实际 {window.brain.state}",
        )

    check("睡觉时被摸会醒来", t_wake_on_pet)

    def t_leave_resets():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        window._update_pet(point_at(window, 0.5, 0.5))
        assert_true(window._hovering, "先进入互动态")
        window._update_pet(point_at(window, 0.02, 0.02))
        assert_true(not window._hovering, "移到透明区应退出互动态")
        assert_true(window._pet_last_pos is None, "退出后应清掉上一个位置")

    check("移出身体退出互动", t_leave_resets)

    print("[3] 抚摸累计与大反应")

    def t_stroke_count():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        # 在身体上来回一次：第 1 个点进入互动态，第 2 个点累计 60px
        a = point_at(window, 0.25, 0.5)
        b = point_at(window, 0.75, 0.5)
        window._update_pet(a)
        window._update_pet(b)
        assert_true(window._pet_strokes == 1, f"应记 1 次抚摸，实际 {window._pet_strokes}")

    check("累计位移达标记一次抚摸", t_stroke_count)

    def t_no_stroke_when_still():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        pos = point_at(window, 0.5, 0.5)
        for _ in range(5):
            window._update_pet(pos)
        assert_true(window._pet_strokes == 0, "鼠标不动不应累计抚摸")

    check("鼠标不动不累计抚摸", t_no_stroke_when_still)

    def t_big_reaction():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        window._cancel_pending_jumps()
        # 每次来回算一次抚摸，多送几次确保跨过阈值
        for _ in range(config.PET_BIG_REACTION + 2):
            window._update_pet(point_at(window, 0.25, 0.5))
            window._update_pet(point_at(window, 0.75, 0.5))
        assert_true(
            window._pet_strokes < config.PET_BIG_REACTION,
            f"触发后计数应归零重来，实际 {window._pet_strokes}",
        )
        # 跳跃是延时排队的（offscreen 无事件循环不会真的跳），看排了几个定时器
        assert_true(
            len(window._jump_timers) == 2,
            f"大反应应排 2 次跳，实际 {len(window._jump_timers)}",
        )
        assert_true(window._override_frame == "laugh", "大反应应保持笑帧")
        window._cancel_pending_jumps()

    check("摸够次数触发大反应", t_big_reaction)

    def t_big_reaction_silent():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        window._cancel_pending_jumps()
        old = config.is_silent_now
        config.is_silent_now = lambda: True
        try:
            window._big_pet_reaction()
            assert_true(len(window._jump_timers) == 0, "静默时大反应不应安排跳跃")
            assert_true(window._override_frame == "laugh", "静默时仍切笑帧（有反应但不动）")
        finally:
            config.is_silent_now = old
            window._cancel_pending_jumps()

    check("静默时大反应只留表情", t_big_reaction_silent)

    print("[4] 静默 / 离开 / 开关")

    def t_silent_no_bounce():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        old = config.is_silent_now
        config.is_silent_now = lambda: True
        try:
            calls["bounce"] = 0
            # 落地 + 抚摸：确认静默时 _pet_bounce 被调起但内部自行跳过
            window._update_pet(point_at(window, 0.25, 0.5))
            window._update_pet(point_at(window, 0.75, 0.5))
            assert_true(window._hovering, "静默时仍应识别互动（只是不动）")
            assert_true(calls["bounce"] == 1, "仍调用 _pet_bounce（内部自行跳过）")
            assert_true(window._pet_anim is None, "静默时不应真的起跳/弹动")
        finally:
            config.is_silent_now = old

    check("静默时摸头不弹动", t_silent_no_bounce)

    def t_away_noop():
        install_body(window)
        reset_pet(window)
        window._away = True
        try:
            calls["bounce"] = 0
            window._update_pet(point_at(window, 0.5, 0.5))
            assert_true(not window._hovering, "离开期间不应响应摸头")
            assert_true(calls["bounce"] == 0, "离开期间不应有反馈")
        finally:
            window._away = False

    check("离开（锁屏）期间不响应", t_away_noop)

    def t_disabled_noop():
        install_body(window)
        reset_pet(window)
        old = config.get("pet_enabled")
        config.set_value("pet_enabled", False)
        try:
            calls["bounce"] = 0
            window._update_pet(point_at(window, 0.5, 0.5))
            assert_true(not window._hovering, "关闭摸头互动后不应响应")
            assert_true(calls["bounce"] == 0, "关闭后不应有反馈")
        finally:
            config.set_value("pet_enabled", old)

    check("关闭摸头互动后不响应", t_disabled_noop)

    def t_set_pet_enabled_ends():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        window._update_pet(point_at(window, 0.5, 0.5))
        assert_true(window._hovering, "先进入互动态")
        window.set_pet_enabled(False)
        assert_true(not window._hovering, "关掉开关应立即结束互动")
        window.set_pet_enabled(True)

    check("关开关立即结束进行中的互动", t_set_pet_enabled_ends)

    print("[5] 动画与台词保护")

    def t_bounce_not_stacked():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        window._pet_bouncing = True  # 模拟上一次弹动还没结束
        try:
            window._pet_anim = None
            window._pet_bounce()
            assert_true(window._pet_anim is None, "弹动进行中不应再起新动画")
        finally:
            window._pet_bouncing = False

    check("弹动不叠加（不会卡在半空）", t_bounce_not_stacked)

    def t_bounce_blocked_by_drag():
        install_body(window)
        reset_pet(window)
        window._drag = True
        try:
            window._pet_bounce()
            assert_true(window._pet_anim is None, "拖拽中不应弹动")
        finally:
            window._drag = False

    check("拖拽中不弹动", t_bounce_blocked_by_drag)

    def t_quote_cooldown():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        window.bubble.hide()
        calls["quote"] = 0
        window._maybe_pet_quote(config.get_pet_messages())
        window._maybe_pet_quote(config.get_pet_messages())
        assert_true(calls["quote"] == 1, f"冷却内应只说一次，实际 {calls['quote']}")

    check("台词冷却生效", t_quote_cooldown)

    def t_quote_not_steal_bubble():
        install_body(window)
        reset_pet(window)
        window._last_pet_quote_at = 0.0
        window.bubble.show_text("重要提醒", window)
        try:
            calls["quote"] = 0
            window._maybe_pet_quote(config.get_pet_messages())
            assert_true(calls["quote"] == 0, "提醒气泡显示时不应被摸头台词顶掉")
        finally:
            window.bubble.hide()

    check("摸头台词不抢提醒气泡", t_quote_not_steal_bubble)

    print("[6] 事件接线")

    def t_mouse_tracking_on():
        assert_true(window.hasMouseTracking(), "窗口必须开启 mouseTracking 才能收 move 事件")
        assert_true(
            window.label.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents),
            "图片标签必须透传鼠标事件，否则 move 事件会被它吃掉",
        )

    check("鼠标事件接线正确", t_mouse_tracking_on)

    def t_move_event_routes():
        install_body(window)
        reset_pet(window)
        window.brain.state = PetBrain.IDLE
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        pos = QPointF(point_at(window, 0.5, 0.5))
        ev = QMouseEvent(
            QEvent.Type.MouseMove,
            pos,
            pos,
            pos,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
        )
        window.mouseMoveEvent(ev)
        assert_true(window._hovering, "真实 move 事件应驱动摸头互动")

    check("mouseMoveEvent 驱动摸头", t_move_event_routes)

    def t_drag_still_works():
        install_body(window)
        reset_pet(window)
        from PySide6.QtCore import QEvent, QPointF
        from PySide6.QtGui import QMouseEvent

        window._drag = True
        window._press_global = QPoint(0, 0)
        window._win_origin = window.pos()
        pos = QPointF(60.0, 60.0)
        ev = QMouseEvent(
            QEvent.Type.MouseMove,
            pos,
            pos,
            QPointF(60.0, 60.0),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        try:
            window.mouseMoveEvent(ev)
            assert_true(window._moved, "拖拽时仍应判定为已移动")
            assert_true(not window._hovering, "拖拽时不应触发摸头")
        finally:
            window._drag = False
            window._moved = False

    check("拖拽优先于摸头", t_drag_still_works)

    print()
    print(f"结果：{PASS} 通过 / {FAIL} 失败")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
