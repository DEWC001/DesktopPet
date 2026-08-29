"""批量处理图生图素材：rembg AI 抠图 -> 对齐 -> 缩放 -> 生成精灵帧。

可复用：新形象只需把原始图放进 raw/ 目录并更新 FRAMES 映射，重新运行。

流程：
  1. rembg AI 抠图（不受前景/背景颜色相似影响）
  2. 裁剪主体 bbox
  3. 统一缩放到 FRAME_H 高度
  4. 底部对齐 + 水平居中到统一画布（保证帧间切换不跳动）
  5. 从 idle 程序生成闭眼 blink 帧
"""
import os
import sys
from collections import deque

from PIL import Image, ImageDraw
from rembg import remove

SKINS_DIR = r"D:\杂\桌宠\assets\skins"
RAW_DIR = r"D:\杂\桌宠\raw"
OUT_DIR = SKINS_DIR
FRAME_H = 240
CANVAS_W = 260
CANVAS_H = 260

# raw 文件名 -> 输出精灵帧名（jump 需额外上移，模拟离地）
FRAMES = {
    "raw_idle.png": "idle.png",
    "raw_walk_a.png": "walk_a.png",
    "raw_walk_b.png": "walk_b.png",
    "raw_jump.png": "jump.png",
    "raw_sleep.png": "sleep.png",
}
JUMP_LIFT = 26  # 跳跃帧上移像素（脚离地）


def remove_bg(path: str) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    return remove(img)


def find_bbox(img: Image.Image):
    px = img.load()
    w, h = img.size
    minx = miny = 10 ** 9
    maxx = maxy = -1
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > 10:  # 忽略半透明噪点
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
    return minx, miny, maxx, maxy


def find_eyes(img: Image.Image):
    """上半脸找深色眼睛像素，左右分簇，返回 [(cx, cy, r), ...]。"""
    px = img.load()
    w, h = img.size
    midy = int(h * 0.58)
    dark = [
        (x, y)
        for y in range(midy)
        for x in range(w)
        if px[x, y][3] > 0 and px[x, y][0] < 80 and px[x, y][1] < 80 and px[x, y][2] < 80
    ]
    if len(dark) < 20:
        return [(int(w * 0.37), int(h * 0.42), 14), (int(w * 0.63), int(h * 0.42), 14)]

    def cluster(pts):
        if not pts:
            return None
        cx = sum(p[0] for p in pts) // len(pts)
        cy = sum(p[1] for p in pts) // len(pts)
        xs = [p[0] for p in pts]
        r = max(5, (max(xs) - min(xs)) // 2 + 4)
        return cx, cy, r

    left = cluster([p for p in dark if p[0] < w // 2])
    right = cluster([p for p in dark if p[0] >= w // 2])
    eyes = [e for e in (left, right) if e]
    return eyes or [(int(w * 0.37), int(h * 0.42), 14), (int(w * 0.63), int(h * 0.42), 14)]


def make_blink(idle: Image.Image, eyes) -> Image.Image:
    blink = idle.copy()
    draw = ImageDraw.Draw(blink)
    px = idle.load()
    w, h = idle.size
    for cx, cy, r in eyes:
        sy = max(0, cy - int(r * 2.2))
        sx = min(w - 1, max(0, cx))
        skin = px[sx, sy][:3]
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=skin)
        draw.arc(
            (cx - r, cy - int(r * 0.7), cx + r, cy + int(r * 0.7)),
            start=200, end=340,
            fill=(70, 70, 80, 255),
            width=max(2, r // 3),
        )
    return blink


def align_to_canvas(img: Image.Image, lift: int = 0) -> Image.Image:
    """统一缩放 + 底部对齐 + 水平居中；lift 为额外上移量。"""
    bbox = find_bbox(img)
    bx0, by0, bx1, by1 = bbox
    cropped = img.crop((bx0, by0, bx1 + 1, by1 + 1))
    bh = by1 - by0 + 1
    scale = FRAME_H / bh
    new_w = max(1, int(cropped.width * scale))
    resized = cropped.resize((new_w, FRAME_H), Image.LANCZOS)

    canvas = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    x = (CANVAS_W - new_w) // 2
    y = CANVAS_H - FRAME_H - lift
    canvas.paste(resized, (x, y), resized)
    return canvas


def main() -> int:
    idle_img = None
    idle_eyes = None
    for raw_name, out_name in FRAMES.items():
        path = os.path.join(RAW_DIR, raw_name)
        if not os.path.exists(path):
            print(f"[跳过] 缺失 {raw_name}")
            continue
        img = remove_bg(path)
        lift = JUMP_LIFT if out_name == "jump.png" else 0
        frame = align_to_canvas(img, lift=lift)
        frame.save(os.path.join(OUT_DIR, out_name))
        print(f"[完成] {out_name} <- {raw_name} ({frame.size})")
        if out_name == "idle.png":
            idle_img = frame
            idle_eyes = find_eyes(frame)

    if idle_img is not None:
        blink = make_blink(idle_img, idle_eyes)
        blink.save(os.path.join(OUT_DIR, "blink.png"))
        print(f"[完成] blink.png <- idle.png, 眼睛 {idle_eyes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
