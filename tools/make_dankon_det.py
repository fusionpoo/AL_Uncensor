#!/usr/bin/env python3
"""make_dankon_det.py — extract cm_dankon_00_det (glans detail mask) from the Aicomi hardmod body bundle and
write it as the plugin's raw cm_dankon_00_det.rg (header 'ALDT' + width + height, then R,G bytes, bottom row first)."""
import argparse, struct, numpy as np, UnityPy, UnityPy.config
from PIL import Image
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.34f1"
ap = argparse.ArgumentParser(); ap.add_argument("--ac", required=True); ap.add_argument("--out", required=True); ap.add_argument("--size", type=int, default=1024)
a = ap.parse_args()
for o in UnityPy.load(a.ac).objects:
    if o.type.name == "Texture2D" and o.read().m_Name == "cm_dankon_00_det":
        im = o.read().image.convert("RGBA").resize((a.size, a.size), Image.LANCZOS); arr = np.array(im)
        open(a.out, "wb").write(struct.pack("<4sII", b"ALDT", a.size, a.size) + arr[::-1, :, :2].astype(np.uint8).tobytes())
        print(f"wrote {a.out} ({a.size}x{a.size})"); break
else: raise SystemExit("cm_dankon_00_det not found")
