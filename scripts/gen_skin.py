"""皮肤素材预处理：AI 生成图 -> 抠背景 -> 裁剪 -> 缩放 -> 程序生成闭眼帧。

可复用：替换 SRC 指向新形象，重新运行即可生成 idle.png + blink.png。
"""
import sys
from collections import deque

from PIL import Image, ImageDraw

SRC = r"D:\杂\桌宠\assets\skins\cute_chibi_round_penguin_masco_2026-08-28T11-34-23.png"
OUT_DIR = r"D:\杂\桌宠\assets\skins"
OUT_IDLE = OUT_DIR + r"\idle.png"
OUT_BLINK = OUT_DIR + r"\blink.png"
DISPLAY_H = 240
BG_THRESH = 60.0  # 背景颜色欧氏距离阈值


def bfs_remove_background(img: Image.Image) -> Image.Image:
    """从四角 BFS 连通抠掉接近背景色的区域，保留主体。"""
    px = img.load()
    w, h = img.size
    seed = px[2, 2][:3]
    th2 = BG_THRESH ** 2
    visited = bytearray(w * h)
    q = deque([(2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3)])
    while q:
        x, y = q.popleft()
        idx = y * w + x
        if visited[idx]:
            continue
        visited[idx] = 1
        r, g, b, a = px[x, y]
        d = (r - seed[0]) ** 2 + (g - seed[1]) ** 2 + (b - seed[2]) ** 2
        if d > th2:
            continue
        px[x, y] = (r, g, b, 0)
        if x > 0:
            q.append((x - 1, y))
        if x < w - 1:
            q.append((x + 1, y))
        if y > 0:
            q.append((x, y - 1))
        if y < h - 1:
            q.append((x, y + 1))
    return img


def find_bbox(img: Image.Image):
    px = img.load()
    w, h = img.size
    minx = miny = 10 ** 9
    maxx = maxy = -1
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > 0:
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
    return minx, miny, maxx, maxy


def find_eyes(img: Image.Image):
    """在上半脸找深色(眼睛)像素，按左右分簇，返回 [(cx, cy, r), ...]。"""
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

    left = [p for p in dark if p[0] < w // 2]
    right = [p for p in dark if p[0] >= w // 2]

    def cluster(pts):
        if not pts:
            return None
        cx = sum(p[0] for p in pts) // len(pts)
        cy = sum(p[1] for p in pts) // len(pts)
        xs = [p[0] for p in pts]
        r = max(5, (max(xs) - min(xs)) // 2 + 4)
        return cx, cy, r

    eyes = [e for e in (cluster(left), cluster(right)) if e]
    return eyes if eyes else [(int(w * 0.37), int(h * 0.42), 14), (int(w * 0.63), int(h * 0.42), 14)]


def make_blink(idle: Image.Image, eyes) -> Image.Image:
    """在眼睛位置填充肤色并画闭眼弧线，生成 blink 帧。"""
    blink = idle.copy()
    draw = ImageDraw.Draw(blink)
    px = idle.load()
    w, h = idle.size
    for cx, cy, r in eyes:
        # 眼睛上方取肤色
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


def main() -> int:
    img = Image.open(SRC).convert("RGBA")
    img = bfs_remove_background(img)
    bx0, by0, bx1, by1 = find_bbox(img)
    # 加少量内边距并裁剪
    pad = 4
    bx0, by0 = max(0, bx0 - pad), max(0, by0 - pad)
    bx1, by1 = min(img.width - 1, bx1 + pad), min(img.height - 1, by1 + pad)
    img = img.crop((bx0, by0, bx1 + 1, by1 + 1))

    eyes = find_eyes(img)

    # 缩放到显示尺寸
    img.thumbnail((2048, DISPLAY_H), Image.LANCZOS)
    scale = DISPLAY_H / (by1 - by0 + 1)
    scaled_eyes = [(int(cx * scale), int(cy * scale), max(4, int(r * scale))) for cx, cy, r in eyes]

    img.save(OUT_IDLE)
    print(f"idle.png saved: {img.size}, 眼睛: {scaled_eyes}")

    blink = make_blink(img, scaled_eyes)
    blink.save(OUT_BLINK)
    print(f"blink.png saved: {blink.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
