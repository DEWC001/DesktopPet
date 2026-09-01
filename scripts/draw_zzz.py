"""在皮肤 sleep.png 上绘制 ZZZ（三个 Z 从左下到右上递减，模拟呼噜冒出）。

参考默认企鹅第十二轮做法：白色 fill + 蓝灰描边 (110,140,180)，
微软雅黑粗体 (msyhbd.ttc)，位置在画面右上角空白处（不挡主体）。

用法：
    python scripts/draw_zzz.py feidudu          # 处理 assets/skins/feidudu/sleep.png
    python scripts/draw_zzz.py default          # 处理 assets/skins/sleep.png
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont


# ZZZ 配置：每个 Z 是 (x_start, y_start, font_size)
# 三个 Z 从左下到右上递进，模拟从主体呼出飘向天空
SKIN_ZZZ = {
    # 三个 Z 由下到上、由大到小：最靠近主体在左下，最大；最远离主体在右上，最小
    "feidudu": [(130, 40, 42), (165, 18, 34), (195, 0, 28)],
    "default": [(100, 24, 50), (132, 58, 42), (162, 90, 36)],  # 原企鹅（保留兼容）
}
FILL = (255, 255, 255, 255)
STROKE = (110, 140, 180, 255)
STROKE_W = 3
FONT_PATH = "C:/Windows/Fonts/msyhbd.ttc"


def draw_zzz(skin: str) -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if skin == "default":
        png = os.path.join(root, "assets", "skins", "sleep.png")
    else:
        png = os.path.join(root, "assets", "skins", skin, "sleep.png")
    if not os.path.exists(png):
        print(f"[ERR] 找不到 {png}")
        sys.exit(1)
    im = Image.open(png).convert("RGBA")
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    for x, y, size in SKIN_ZZZ[skin]:
        font = ImageFont.truetype(FONT_PATH, size)
        # 右对齐 + 顶对齐：先用 textbbox 算宽高再贴
        bbox = draw.textbbox((0, 0), "Z", font=font, stroke_width=STROKE_W)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text(
            (x, y), "Z",
            font=font,
            fill=FILL,
            stroke_width=STROKE_W,
            stroke_fill=STROKE,
        )
    out = Image.alpha_composite(im, overlay)
    out.save(png)
    print(f"[OK] {skin} sleep.png 已绘制 ZZZ → {png}")


if __name__ == "__main__":
    skin = sys.argv[1] if len(sys.argv) > 1 else "feidudu"
    if skin not in SKIN_ZZZ:
        print(f"[ERR] 未知皮肤 {skin}，可选: {list(SKIN_ZZZ.keys())}")
        sys.exit(1)
    draw_zzz(skin)
