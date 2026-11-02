#!/usr/bin/env bash
# Rebuilds lib/chara/body/body_00.unity3d and the plugin's data files from a VANILLA Amanatsu bundle and
# DilleDing's Aicomi hardmod bundle (ACUncensorHardmod body_00.unity3d, e.g. from the Aicomi HF Patch).
#   ./build_bundle.sh <vanilla AL body_00.unity3d> <Aicomi hardmod body_00.unity3d> [outdir]
# Needs: python3 with UnityPy, numpy, scipy, trimesh, rtree, pillow   (pip install UnityPy numpy scipy trimesh rtree pillow)
set -euo pipefail
AL=${1:?vanilla Amanatsu body_00.unity3d}; AC=${2:?Aicomi hardmod body_00.unity3d}; OUT=${3:-build}
T="$(dirname "$0")/tools"; mkdir -p "$OUT"
python3 "$T/inject_dankon2.py"  --al "$AL" --ac "$AC" --out "$OUT/body_00.step1.unity3d" --girth 0.85          # penis (own UV layout, 15% thinner)
python3 "$T/merge_female.py"    --al "$OUT/body_00.step1.unity3d" --ac "$AC" --out "$OUT/body_00.unity3d" \
                                --keep-uv --perineum 0.30 --labia-mask "$OUT/labia_mask.r"                       # vulva + anus stitched into the body
python3 "$T/merge_female.py"    --al "$AL" --ac "$AC" --out "$OUT/body_00.female.unity3d" --keep-uv --perineum 0.30     # female-only variant
python3 "$T/make_dankon_det.py" --ac "$AC" --out "$OUT/cm_dankon_00_det.rg"                                       # glans mask for the plugin
rm -f "$OUT/body_00.step1.unity3d"
echo "done: $OUT/body_00.unity3d, $OUT/body_00.female.unity3d, $OUT/labia_mask.r, $OUT/cm_dankon_00_det.rg"
