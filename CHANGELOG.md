# Changelog
## 0.9.1
- Penis girth reduced 15% (`inject_dankon2.py --girth 0.85`, radial scale about the shaft axis; the base stays buried in the body).
- Female-only mode: with "Uncensor males" off the plugin serves `body_00.female.unity3d` (vanilla penis) and the male mosaic stays untouched. "Body bundle file" is now an override, empty by default.
## 0.9.0
- Hardmod bundle is served from the plugin folder via an `AssetBundle.LoadFromFile` hook; the game's `body_00.unity3d` stays vanilla. Install is now a single plugin folder.
## 0.8.0
- Pink tint inside the labia via the body's `_Detail_mask_02` layer (config "Vulva pink tint").
## 0.7.x
- Penis uses DilleDing's UV layout with a glans detail mask and a skin-tone base colour sampled at runtime.
- Vertex colours = object-space smoothed normals on all ported geometry.
- Hardmod v16: vulva/perineum/anus stitched into all nine female crotch meshes as one closed surface (v13),
  conform step confined to the rim band (v15), folded bridge triangles fixed (v16).
## 0.6.0
- Pubic-hair mask applied to the body material (merged hardmod no longer needs a separate patch material).
## 0.5.x and earlier
- Material swap plugin, ForceShow outside H, first overlay-patch hardmods.
