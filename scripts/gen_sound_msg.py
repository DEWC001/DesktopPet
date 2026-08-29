"""生成新消息提醒提示音：轻快的"滴嘟"两声（较高频，像聊天软件消息提示）。"""
import math
import os
import struct
import sys
import wave

SR = 44100
OUT = r"D:\杂\桌宠\assets\sounds\msg.wav"


def tone(freq: float, dur: float, vol: float) -> list:
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        env = math.exp(-6.0 * t / dur)
        s = vol * env * (
            0.75 * math.sin(2 * math.pi * freq * t)
            + 0.25 * math.sin(2 * math.pi * freq * 2 * t)
        )
        out.append(int(max(-1.0, min(1.0, s)) * 32767))
    return out


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # 滴（高音短） + 嘟（稍低音短），比喝水的叮咚更轻快
    samples = tone(1567.98, 0.10, 0.45) + tone(1174.66, 0.14, 0.42)
    with wave.open(OUT, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    print(f"saved {OUT} ({len(samples) / SR:.2f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
