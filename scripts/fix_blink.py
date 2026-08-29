"""修复 blink 帧：用连通域聚类精确定位眼睛，重新生成闭眼帧。"""
import sys
from collections import deque

from PIL import Image, ImageDraw

IDLE = r"D:\杂\桌宠\assets\skins\idle.png"
BLINK = r"D:\杂\桌宠\assets\skins\blink.png"


def find_eyes(px, w, h):
    """上半脸深色像素连通域聚类，取最大的两个作为眼睛。"""
    dark = set()
    for y in range(int(h * 0.45)):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 10 and r < 100 and g < 100 and b < 100:
                dark.add((x, y))
    clusters = []
    while dark:
        seed = next(iter(dark))
        dark.discard(seed)
        q = deque([seed])
        pts = [seed]
        while q:
            x, y = q.popleft()
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if (nx, ny) in dark:
                    dark.discard((nx, ny))
                    q.append((nx, ny))
                    pts.append((nx, ny))
        if len(pts) >= 20:
            clusters.append(pts)
    clusters.sort(key=lambda c: -len(c))
    eyes = []
    for c in clusters[:2]:
        xs = [p[0] for p in c]
        ys = [p[1] for p in c]
        cx = sum(xs) // len(xs)
        cy = sum(ys) // len(ys)
        r = max(8, min(16, (max(xs) - min(xs)) // 2 + 2))
        eyes.append((cx, cy, r))
    eyes.sort(key=lambda e: e[0])
    return eyes


def main() -> int:
    idle = Image.open(IDLE).convert("RGBA")
    px = idle.load()
    w, h = idle.size
    eyes = find_eyes(px, w, h)
    print(f"眼睛: {eyes}")

    if len(eyes) < 2:
        # 回退到固定比例坐标（企鹅正面）
        eyes = [(int(w * 0.38), int(h * 0.33), 10), (int(w * 0.62), int(h * 0.33), 10)]
        print(f"回退固定坐标: {eyes}")

    blink = idle.copy()
    draw = ImageDraw.Draw(blink)
    for cx, cy, r in eyes:
        skin = px[cx, max(0, cy - r * 2)][:3]
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=skin)
        draw.arc(
            (cx - r, cy - r // 2, cx + r, cy + r // 2),
            start=200, end=340,
            fill=(60, 60, 70, 255),
            width=max(2, r // 3),
        )
    blink.save(BLINK)
    print(f"blink.png saved ({blink.size})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
