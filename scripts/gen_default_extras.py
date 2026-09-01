"""为默认企鹅皮肤（assets/skins/）生成 drink / think / laugh 三个扩展帧。

基于 idle.png 合成（PIL 透明叠加）。原图位置信息：
    - 图片尺寸 260x260
    - 左眼中心 (96, 81)，右眼中心 (161, 80)
    - 嘴巴橙色中心 (129, 89)
与 feidudu 那种由 ImageGen 出的素材相比，本方法只是占位——
让默认皮肤也能用上扩展帧逻辑（喝水时用 drink 图、双击有笑、自语有思考表情）。
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

SKINS = r"D:\杂\桌宠\assets\skins"

# (左眼 cx, cy, r), (右眼 cx, cy, r)；基于 idle.png 实际像素聚类结果
IDLE_EYES = [(96, 81, 12), (161, 80, 12)]
BEAK = (129, 89)  # 嘴巴中心
FONT_PATH = r"C:\Windows\Fonts\msyhbd.ttc"


def _new_overlay(size):
    return Image.new("RGBA", size, (0, 0, 0, 0))


def make_drink(src: Image.Image) -> Image.Image:
    """drink：右下角画一个水杯（角色被提醒喝水时的视觉）。"""
    out = _new_overlay(src.size)
    draw = ImageDraw.Draw(out)
    # 杯体居中偏左下，覆盖部分身体
    cup_x, cup_y, cup_w, cup_h = 75, 170, 55, 65
    draw.rounded_rectangle(
        [cup_x, cup_y, cup_x + cup_w, cup_y + cup_h],
        radius=6,
        fill=(255, 255, 255, 235),
        outline=(150, 150, 150, 255),
        width=2,
    )
    # 水位线（蓝色）
    water_top = cup_y + int(cup_h * 0.45)
    draw.rectangle(
        [cup_x + 4, water_top, cup_x + cup_w - 4, cup_y + cup_h - 4],
        fill=(170, 210, 240, 200),
    )
    # 杯口椭圆（顶部装饰）
    draw.ellipse(
        [cup_x, cup_y - 3, cup_x + cup_w, cup_y + 6],
        outline=(150, 150, 150, 255),
        width=2,
    )
    # 杯把手（右侧弧）
    draw.arc(
        [cup_x + cup_w, cup_y + int(cup_h * 0.25),
         cup_x + cup_w + 18, cup_y + int(cup_h * 0.65)],
        start=310, end=50,
        fill=(150, 150, 150, 255),
        width=3,
    )
    return Image.alpha_composite(src, out)


def make_think(src: Image.Image) -> Image.Image:
    """think：头顶思考泡泡 + 三个递减小气泡 + 问号。"""
    out = _new_overlay(src.size)
    draw = ImageDraw.Draw(out)
    # 三个气泡（最大的在右上，依次减小往下）
    bubbles = [(195, 45, 30), (175, 75, 10), (163, 92, 6)]
    for cx, cy, r in bubbles:
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(255, 255, 255, 245),
            outline=(110, 110, 110, 255),
            width=2,
        )
    # 大泡泡里的问号
    try:
        font = ImageFont.truetype(FONT_PATH, 30)
        bbox = draw.textbbox((0, 0), "?", font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        cx, cy, _r = bubbles[0]
        draw.text(
            (cx - tw // 2 - bbox[0], cy - th // 2 - bbox[1]),
            "?",
            fill=(60, 60, 60, 255),
            font=font,
        )
    except Exception:
        # 字体不可用时用黑色椭圆作为问号占位
        cx, cy, _r = bubbles[0]
        draw.ellipse([cx - 4, cy - 6, cx + 4, cy + 6], fill=(60, 60, 60, 255))
    return Image.alpha_composite(src, out)


def make_laugh(src: Image.Image) -> Image.Image:
    """laugh：眯眼笑 + 嘴巴改大笑弧。"""
    out = _new_overlay(src.size)
    draw = ImageDraw.Draw(out)
    # 取眼睛上方的肤色覆盖眼睛区域（含亮星），避免出现"白眼球+笑线"的违和
    for cx, cy, r in IDLE_EYES:
        skin = src.getpixel((cx, max(0, cy - r * 2)))[:3]
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(*skin, 255),
        )
        # 画上凸笑弧（眯眼，月牙朝下 = 笑）
        draw.arc(
            [cx - r, cy - int(r * 0.7), cx + r, cy + int(r * 0.7)],
            start=200, end=340,
            fill=(60, 60, 60, 255),
            width=max(2, r // 3),
        )
    # 嘴巴：取嘴下方白色（肚子色）覆盖原嘴，再画大笑弧
    bx, by = BEAK
    skin_color = src.getpixel((bx, by + 25))[:3]
    draw.rectangle([bx - 16, by - 14, bx + 16, by + 14], fill=(*skin_color, 255))
    draw.arc(
        [bx - 15, by - 6, bx + 15, by + 24],
        start=0, end=180,
        fill=(60, 60, 60, 255),
        width=3,
    )
    return Image.alpha_composite(src, out)


def main() -> int:
    idle_path = os.path.join(SKINS, "idle.png")
    if not os.path.exists(idle_path):
        print(f"[错误] 缺失 {idle_path}")
        return 1
    src = Image.open(idle_path).convert("RGBA")
    src.load()
    print(f"加载 {idle_path} {src.size}")

    make_drink(src).save(os.path.join(SKINS, "drink.png"))
    print("[完成] drink.png")

    make_think(src).save(os.path.join(SKINS, "think.png"))
    print("[完成] think.png")

    make_laugh(src).save(os.path.join(SKINS, "laugh.png"))
    print("[完成] laugh.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())