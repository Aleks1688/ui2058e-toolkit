# -*- coding: utf-8 -*-
"""Разбор 40-байтных кадров из raw-лога перехвата: печатает все 10 float.

    python analyze_block.py [captures/raw_XXX.log]

Без аргумента берёт самый свежий captures/raw_*.log.
"""
import glob
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

if len(sys.argv) > 1:
    LOG = sys.argv[1]
else:
    logs = glob.glob(os.path.join(ROOT, "captures", "raw_*.log"))
    if not logs:
        sys.exit("нет логов в captures/ — сначала запустите tools/capture_live.py")
    LOG = max(logs, key=os.path.getmtime)

frames = []
values = []
for line in open(LOG, encoding="utf-8", errors="replace"):
    if " READ len=40:" in line:
        hexs = line.split("len=40:")[1].strip()
        frames.append((line.strip(), struct.unpack("<10f", bytes.fromhex(hexs))))
    elif " READ len=60:" in line:
        hexs = line.split("len=60:")[1].strip()
        values.append(struct.unpack("<15f", bytes.fromhex(hexs)))

print("log:", LOG)
print("40-byte frames:", len(frames), " 60-byte frames:", len(values))
print()
print("%-14s %10s %10s %10s %10s %10s | %10s %10s %10s %10s %10s" % (
    "time", "Ulamp", "Ilamp", "Pout", "IlrmsHi", "Effic", "t5", "t6", "t7", "t8", "t9"))
for line, f in frames[:12]:
    t = line.split(" ")[0]
    print("%-14s %10.4f %10.5f %10.4f %10.5f %10.5f | %10.4f %10.4f %10.4f %10.3f %10.3f" % (
        t, f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9]))

print()
if frames and values:
    v = values[-1]
    f = frames[-1][1]
    pin = v[2]
    pout = f[2]
    print("проверка: Pin=%.4f W  Pout=%.4f W  Pout/Pin=%.5f  Efficiency(поле)=%.5f  Ulamp*Ilamp=%.4f" % (
        pin, pout, pout / pin if pin else 0, f[4], f[0] * f[1]))