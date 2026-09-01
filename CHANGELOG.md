# Changelog

本项目所有重要变更都会记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.3.0] - 2026-09-01

> 新增**离开感知**：锁屏/离开时桌宠自动静默，回来时补报未读消息与错过的
> 提醒事项。同时修掉久坐提醒「离开两小时回来立刻催你起身」的体验问题。

### 新增

- **离开感知（锁屏自动静默）**：通过 `WTSRegisterSessionNotification` 订阅
  Windows 会话通知（`WM_WTSSESSION_CHANGE`），锁屏/解锁由系统主动推送，
  零轮询开销。托盘新增「离开时静默」开关（默认开）。
  - `pet/session_monitor.py`：封装注册/注销/消息解析。
  - 离开期间：不响铃、不跳跃、不跑到屏幕中心、不弹气泡。
- **回来补报**：解锁后弹一条汇总（离开 ≥1 分钟才报，快速锁一下屏不打扰）：
  ```
  欢迎回来～你离开了 1 小时 30 分钟
  灵犀、微信 有未读消息；错过提醒：该吃药了、取快递
  ```
  超过 5 条折叠为「… 等 N 条」。
- **提醒分类处理**（离开期间）：
  - 有时效性的**自定义提醒事项**（吃药/周会/取快递）→ 记下来，回来补报
  - **周期提醒**（喝水/久坐/整点/下班）→ 直接丢弃，回来重新计时
  - **IM 未读** → 不逐条打扰，回来统一汇报哪些应用有未读

### 修复

- **久坐提醒在离开期间照常倒计时**：离开两小时后一回来就立刻弹「该起身了」。
  现在锁屏时暂停久坐计时，解锁后重新开始一个完整间隔。

### 实现要点（踩过的坑）

- **`WTSUnregisterSessionNotification` 的 R 是大写**：Win32 导出名是
  `WTSUnRegisterSessionNotification`，写成小写 r 会找不到符号。更坑的是
  原本在加载时一次性设置所有函数签名，一个符号缺失就把整个模块判死——
  连 `WTSRegisterSessionNotification` 都用不了。改成逐符号容错。
- **`MSG.from_address()` 不做合法性校验，传负数直接段错误**：比抛异常严重
  得多（测试时真的把解释器打崩了）。`_message_address` 现在拒绝
  ≤0 和超出 64 位地址空间的值。
- **ctypes 缓冲区必须保活**：测试辅助函数 `make_message` 返回裸地址，
  buf 是局部变量时函数一返回就被回收，地址变悬空指针（读出来是垃圾值）。
  现在存进模块级列表保活。
- 离开状态是**纯内存标记**，不写 QSettings——避免程序崩溃后残留「一直在
  离开中」导致提醒永远静默。

### 测试

- **`scripts/test_session_monitor.py`（24 项）**：消息解析（lock/unlock/
  无关消息/垃圾入参）、锁屏幂等、未锁屏时 unlock 无副作用、周期提醒丢弃
  并重新计时、自定义提醒记录、离开期间不弹气泡、补报文案各种组合、
  补报后清空、开关关闭时退出离开态、注册失败优雅降级。
- **`scripts/test_session_e2e.py`（5 项）**：真窗口 + `SendMessage` 投递
  `WM_WTSSESSION_CHANGE`，端到端验证 Qt `nativeEvent` 能收到并正确解析。
  **必须在真实桌面平台运行**（不能设 offscreen，否则拿不到真实 HWND），
  测试窗口会临时挪到屏幕外。用它绕开了「真的去锁屏」这个不可自动化的步骤。

## [1.2.1] - 2026-09-01

> 性能优化专项：IM 未读监听的轮询开销。不改动任何检测逻辑，只降低「什么
> 都没发生时空转」的成本。实机实测单轮耗时 154ms → 65ms（提速 2.38×）。

### 优化

- **自适应降频**：没有任何受监测 IM 在运行时（任务栏按钮 + 顶层窗口标题都
  匹配不到），轮询间隔从 2s 自动降到 15s；一旦检测到目标应用立即恢复 2s。
  空闲时单核占用从 7.71% 降到 0.43%。状态切换只在变化时打一条日志，不刷屏。
- **任务栏控件缓存**：`Shell_TrayWnd` 缓存 300 秒，超时或主动失效时重找。
  附带安全网——若缓存的任务栏一个按钮都取不到（资源管理器重启后旧 UIA
  控件会静默返回空），立即丢弃缓存重找一次，避免长时间漏检未读。
- **`_find_taskbar` 快路径**：任务栏通常是桌面根的直接子节点，先只扫一层，
  命中即返回。改造前为了找任务栏会把每个顶层窗口的子树都递归翻一遍（深度 8）。
- **顶层窗口标题每轮只枚举一次**：改造前 `_window_title_unread` 每个应用各
  枚举一遍全部顶层窗口，4 个应用 = 每秒 2 轮 × 4 次全量遍历。改为懒加载
  `_collect_window_titles()` 收集一次，各应用复用 `_window_title_unread_from()`。

### 兼容性

- 保留 `_window_title_unread(root, keywords)` 原接口（`scripts/test_im_unread.py`
  在用），内部改为委托给新的标题列表版本，行为完全一致。
- **检测结果零变化**：新增 20 项等价性测试，逐一校验按钮角标未读、窗口标题
  兜底、干净状态不误报等核心路径与改造前一致。

### 测试

- **`scripts/test_im_polling.py`（20 项）**：任务栏查找快路径/深层兜底/缺失、
  标题收集与异常兜底、角标判定等价性、缓存命中/TTL/强制刷新/失效重找、
  每轮只枚举一次、降频四种状态转换、检测结果等价性。
- **`scripts/bench_im_polling.py`**：实机 UIA 遍历计时，量化优化前后的
  ms/轮与单核占用百分比。

## [1.2.0] - 2026-09-01

> 本次聚焦「更安静 + 更可定制」：新增静默控制三件套（提示音 / 免打扰时段 /
> 专注模式）、自定义提醒事项、贴边隐藏；修复单击 / 双击区分缺失导致双击多
跳一次；默认企鹅皮肤补齐 drink/think/laugh 扩展帧；提醒计时器拆开可独立刷
新。

### 新增

- **提示音总开关**：托盘新增「提示音」勾选，关闭后所有提醒只弹气泡不响铃
  （开会共享屏幕时不再尴尬）。新增 `config.sound_allowed()` 作为统一判断
  入口。
- **免打扰时段**：托盘「免打扰时段」子菜单。预设（夜间 22:30-08:00 / 23:00
  -07:00 / 午休 12:30-14:00）+ 自定义开始/结束时间。支持跨零点（如
  22:30-08:00）。开启后生效期间：提示音静默、不跳跃、喝水不跑到屏幕中心、
  IM 未读超时强提醒只在原地弹气泡不移动。
- **专注模式**：托盘「专注模式」子菜单。30 / 60 / 120 分钟 + 结束专注。
  菜单标题实时显示「专注中 · 剩 X 分钟」方便看状态。专注中 = 静默。同免
  打扰逻辑（不响不跳不动）。适合开会、写材料等需要专注的场景。
- **自定义提醒事项**：托盘「自定义提醒」子菜单。用户自加提醒：
    - 每天固定时间（如「15:00 该吃药了」）
    - 每周某天（如「每周一 10:00 周会」）
    - 仅一次（如「2026-09-01 16:00 取快递」）
  - 添加对话框用 QTimeEdit / QComboBox / QDateEdit，配置数据 JSON 存
    QSettings。
  - 30 秒轮询 + 当日去重保证不会漏也不会重复触发。
  - 管理对话框支持删除；菜单里每项独立勾选可临时停用。
- **贴边隐藏**：桌宠静止超过 30 秒后自动滑到最近的屏幕边缘只露 20px（避免
  长时间遮挡工作窗口），鼠标移近（窗口外扩 30px 内）自动滑回用户最近拖到
  的位置。托盘「贴边隐藏」勾选可关闭。
- **默认企鹅皮肤补 drink/think/laugh 扩展帧**：之前 `assets/skins/` 根目
  录只有 6 个基础帧，导致默认皮肤下喝水提醒仍是 idle 图、双击没笑脸、自言
  自语没思考表情。现在用 PIL 基于 idle.png 合成：
    - drink：右下角水杯（白色杯体 + 蓝色水位 + 灰色把手）
    - think：头顶思考泡泡（三个递减小气泡 + 大泡泡里的问号）
    - laugh：眯眼笑（眼睛覆盖 + 上凸笑弧）+ 大笑嘴
  生成脚本 `scripts/gen_default_extras.py`，原图备份
  `raw/skins_backup/default_idle_orig.png`。

### 修复

- **单击 / 双击区分（陈反馈「双击也会一直跳」））**：Qt 双击事件序列为
  press → release → dblclick → release，第二次 release 又会触发一次单击
  逻辑，导致双击实际执行「连跳 3 下 + 单击跳 1 下」多跳一次。新增
  `_suppress_click` 标志，doubleClickEvent 触发时设上，第二次 release 检测
  到则直接忽略。
- **双击连跳定时器叠加**：原本用 3 个匿名 `QTimer.singleShot`，快速连点会
  叠加跳动。改为可管理的 `_jump_timers` 池，每次双击前 `_cancel_pending_
  jumps` 取消未触发的。
- **改一个设置重置其他提醒倒计时**：原本 `refresh_reminders()` 一次重启
  4 个计时器，调久坐间隔会把喝水倒计时清零。拆出 `refresh_reminder(kind)`
  按类型精确刷新，托盘各回调改调单个刷新。`refresh_reminders()` 仍保留
  作为全量刷新入口。

### 变更

- **新增 `pet/custom_reminder_dialog.py`**：ReminderEditDialog（添加） +
  ReminderManageDialog（管理删除）。从 tray 模块拆出来单独可读。
- **config 静默控制公共 API**：`is_silent_now()` / `sound_allowed()` /
  `focus_active()` / `quiet_active()` / `set_focus_minutes()`。
- **window 内统一 `_play_sound(name)`**：合并原来的 `_play_drink_sound` /
  `_play_feishu_sound`，内部检查 `sound_allowed()`。
- **`config.get(key, default=None)` 支持可选默认值**：原签名只收 1 个参数，
  UI 层按直觉传兜底值会直接 TypeError。同时新增公开 `config.flag(key)` 作为
  布尔读取入口（兼容 QSettings 回传字符串 `"false"` 被当真的坑）。

### 测试

1.2.0 打包后实跑时炸过一次 `config.get() takes 1 positional argument but 2
were given`——`py_compile` 和纯逻辑单测全绿，只有 exe 构造 TrayIcon 时才暴露。
为此新增两个「真构造对象」的冒烟测试，纳入改动后必跑清单：

- **`scripts/test_menu_smoke.py`（27 项）**：offscreen 平台下真实构造
  PetWindow + TrayIcon，刷新菜单勾选态，并遍历触发全部顶层菜单项
  （可勾选的来回切一次）。模态对话框全部打桩，避免 offscreen 下 exec 挂住。
- **`scripts/test_behavior_smoke.py`（11 项）**：真实构造 QMouseEvent 还原
  Qt 双击序列，校验单击判定定时器、双击抑制标志、连点不叠加连跳；
  贴边隐藏状态机不重入；提醒计时互相独立；自定义提醒到点触发与当日去重；
  静默时只弹气泡不跳。
- **`scripts/test_silence.py`（43 项）**：免打扰跨零点、专注计时、音效叠加
  静默、自定义提醒 CRUD 与周期匹配。

## [1.1.1] - 2026-09-01

> 本次聚焦「体验一致性」：feidudu 皮肤补齐睡觉 ZZZ 视觉、修复扩展帧
> 在切肤/缩放后丢失的隐患与呼吸缓存崩溃风险、状态机改为更活泼的
> 节奏（缩短睡眠、降低回睡概率、增加散步）。

### 新增

- **feidudu 睡觉帧加 ZZZ**：用 PIL 在 `assets/skins/feidudu/sleep.png`
  右上方绘制三个 Z（白底蓝灰描边，由下到上由大到小），模拟从鼻子
  呼出飘向天空。`scripts/draw_zzz.py` 通用（也支持原企鹅 sleep.png，
  作为可重用的素材工具）。原图备份在 `raw/skins_backup/feidudu_sleep_orig.png`。

### 修复

- **扩展帧（drink/think/laugh）在切肤/缩放后丢失**：`set_skin` 和
  `set_scale` 重新加载帧时只重建基础 6 帧，没带扩展帧，导致切到
  feidudu 后 drink 帧消失、喝水提醒无法显示 drink 图。抽
  `_load_all_frames()` 统一加载基础+扩展帧，3 个入口共用。
- **呼吸缓存缺扩展帧，触发 `KeyError` 崩溃**：`_rebuild_breath_cache`
  只缓存 6 个基础帧；`_current_frame_name()` 返回 drink/think/laugh
  时 `_breath_cache[name]` 抛 `KeyError`，呼吸 timer 异常→桌宠静默
  卡死。改为对所有已加载帧都建呼吸缓存。

### 变更

- **状态机更活跃**（`pet/brain.py`）：
  - `SLEEP` 时长 90-240s → **30-80s**（睡眠为主改为睡眠短暂）
  - 活动结束回睡概率 0.8 → **0.45**（多半时间在外面活动）
  - `AWAKE_ACTIONS` 加入 `WANDER`（散步到随机位置，×2 加权），
    解决了"只会睡觉不会移动"的问题

## [1.1.0] - 2026-08-30

> 本次更新围绕「换肤」与「互动性」展开：新增多皮肤支持、全新的
> feidudu（肥嘟嘟）3D 卡通皮肤、皮肤专属台词、动作切换台词气泡，
> 并对素材生产链路（抠图）做了完整梳理。原企鹅皮肤保留为默认皮肤。

### 新增

#### 换肤系统
- **托盘「更换皮肤」菜单**：动态扫描 `assets/skins/` 下含全部 6 个动作帧的
  子目录，互斥单选；切换即时生效（保持窗口中心，托盘图标同步刷新）。
- 皮肤选择持久化到配置（`skin` 键），重启后保留。
- 当前可用皮肤：
  - `默认（企鹅）`：`assets/skins/` 根目录（原版）
  - `feidudu`（肥嘟嘟）：`assets/skins/feidudu/`

#### feidudu（肥嘟嘟）皮肤
- 共 **9 个动作帧**（260×260、透明背景、底部对齐、水平居中）：
  - 基础 6 帧：`idle`（叉腰回头）/ `blink`（单眼闭+捂嘴）/
    `walk_a`（伸手比 V）/ `walk_b`（镜像）/ `jump`（缩放上移）/ `sleep`（闭眼抱物）
  - 扩展 3 帧：`drink`（捧杯喝水）/ `think`（摸头思考）/ `laugh`（捂嘴笑）
- 扩展帧按需加载：皮肤目录里存在则启用对应动作，不存在时自动回退 `idle`，
  对其它皮肤零影响。
- 素材来源：用户提供的 12 张 3D 卡通形象（含报时拿怀表、坐姿鼓肚、捧杯、
  坐键盘、趴地托腮等），经透明化处理后选帧映射。
- 原图配文（如「肥嘟嘟的胆子，在此」）已从动作帧中裁除；右下角抠图水印
  已清除。

#### 台词系统（互动性增强）
- **feidudu 专属台词**：随机自语追加 7 条、点击回应追加 6 条，均带
  「肥嘟嘟」风格（如「你的胆子真是肥嘟嘟的～」「我的胆子，肥嘟嘟的！」）。
  仅在 feidudu 皮肤时混入，默认企鹅皮肤台词保持原样。
- **动作切换台词气泡**：状态机切换动作时随机弹出台词，增强互动：
  - `walk`：出去溜达一圈～ / 肥嘟嘟去巡逻了～
  - `jump`：飞起来啦！ / 胆子肥，跳得高！
  - `sleep`：困了，眯一会儿～ / 胆子鼓鼓，先睡为敬～
  - `wander`：去那边看看 / 肥嘟嘟巡逻时间到
  - `drink`：喝口水润润嗓 / 肚皮嘟嘟，喝水补补
  - `chat`：复用随机自语（feidudu 追加专属台词）
- **台词冷却机制**：同一状态 8 秒内不重复弹气泡，避免频繁切换刷屏。

#### 素材生产链路（开发）
- 新增 `assets/skins/feidudu/` 素材目录与处理脚本（开发产物，不打进 exe）：
  - `_process_v4.py`：cv2 GrabCut 抠图 + 缩放对齐（260×260）
  - `_process_v5_kotu.py`：基于高质量透明原图生成 6 基础帧
  - `_process_v6_extras.py`：生成 drink/think/laugh 扩展帧
  - `_rewalk.py` / `_clear_text.py`：配文裁除辅助脚本

### 变更

- `pet/config.py`：
  - 新增 `skin` 配置项、`DEFAULT_SKIN`、`list_skins()` / `current_skin()`；
  - 新增 `FEIDUDU_MESSAGES` / `FEIDUDU_CLICK_MESSAGES` 专属台词与皮肤感知的
    `get_random_messages()` / `get_click_messages()`；
  - 新增 `ACTION_QUOTES` 动作台词表、`get_action_quotes()`、
    `ACTION_QUOTE_COOLDOWN=8`。
- `pet/window.py`：
  - `_load()` 改为按当前皮肤路径加载 `skins/<皮肤>/<帧>.png`；
  - 新增 `set_skin()` 方法（保存配置、重载帧、重建缓存、居中保持、图标刷新）；
  - 新增 `EXTRA_FRAME_NAMES` 扩展帧加载与 `_override_frame` 临时帧机制
    （双击 1.5s `laugh`、喝水 10s `drink`）；
  - `_current_frame_name()`：CHAT 状态使用 `think` 帧；
  - `_on_state()` 末尾调用 `_emit_action_quote()` 弹动作台词（带冷却）。
- `pet/tray.py`：
  - 新增「更换皮肤」子菜单（动态扫描、互斥单选、`_sync_skin_checks`）；
  - 新增 `_build_idle_icon()` / `refresh_icon()`，皮肤切换后同步托盘图标。
- `assets/skins/`：新增 `feidudu/` 皮肤目录。
- `.gitignore`：新增排除皮肤开发产物（`**/_thumb/`、`**/yuantu/`、`**/kotu/`、
  `**/_process*.py` 等），避免素材中间产物进入仓库。

### 移除

- **删除 `yellow_pet` 皮肤**（2026-08-29 曾新增的 AI 生成测试皮肤）：
  其 6 帧为 AI 生成 RGB 不透明图、带白边羽化，显示效果不佳，已整体移除
  （含目录与 git 跟踪）。

### 修复

- **透明背景问题**：此前 AI 生图请求「透明背景」实际返回 RGB 不透明图，
  桌宠会显示白底方块。现统一改用 **cv2 GrabCut 抠图**（`opencv-python-headless`）
  获得干净的透明背景，角落 alpha=0、无白边。
- **抠图方案迭代**（开发链路）：
  - `rembg` 无法安装（HuggingFace 模型源不可达）→ 弃用；
  - flood fill（边缘采样背景色）在浅黄+浅灰背景上过度抠图 → 弃用；
  - 最终采用 GrabCut + 形态学清理，效果稳定。

### 打包与部署

- `dist/DesktopPet.exe`：onefile 单文件，含全部皮肤资源。
  - 1.1.0 之前（yellow_pet + kotu 素材入包）：约 117~118 MB；
  - 1.1.0（移除 yellow_pet，扩展帧入包）：约 112 MB。

### 已知事项

- 本机 git 推送依赖 PAT（GitHub MCP 连接器 App 为只读权限）。
- `build.bat` 硬编码了原作者的 Python 路径，本机重打包需手动执行
  `pyinstaller` 命令（详见 git 提交说明）。
