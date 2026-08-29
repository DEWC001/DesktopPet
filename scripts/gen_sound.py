"""生成喝水提醒提示音：清脆的"叮咚"两声（正弦波 + 指数衰减）。"""
import math
import os
import struct
import sys
import wave

SR = 44100
OUT = r"D:\杂\桌宠\assets\sounds\drink.wav"


def tone(freq: float, dur: float, vol: float) -> list:
    n = int(SR * dur)
    out = []
    for i in range(n):
        t = i / SR
        # 指数衰减包络 + 基础正弦 + 一个高次泛音让声音更清脆
        env = math.exp(-5.0 * t / dur)
        s = vol * env * (
            0.8 * math.sin(2 * math.pi * freq * t)
            + 0.2 * math.sin(2 * math.pi * freq * 2 * t)
        )
        out.append(int(max(-1.0, min(1.0, s)) * 32767))
    return out


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # 叮（高音短） + 咚（低音长）
    samples = tone(880.0, 0.18, 0.55) + tone(587.33, 0.30, 0.5)
    with wave.open(OUT, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    print(f"saved {OUT} ({len(samples) / SR:.2f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
