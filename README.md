# AL_Uncensor — uncensor for Amanatsu Location

Uncensor mod for **Amanatsu Location** (ILLGAMES, Unity 6 / IL2CPP). Replaces the mosaic with real
geometry for both sexes and installs as a single plugin folder — no game file is modified.

**[Download the latest release](https://github.com/fusionpoo/AL_Uncensor/releases/latest)** ·
**[Documentation](https://fusionpoo.github.io/AL_Uncensor/)**

## Features
- Vulva and anus stitched directly into the female body meshes (one closed surface, no overlay patch,
  nothing to clip or float), ported from DilleDing's Aicomi uncensor hardmod.
- Modeled penis with its own UV layout, glans detail mask and a runtime-sampled skin tone.
- Pubic hair masked off the labia (mons hair kept), soft pink tint inside the slit — both adjustable.
- Works in the maker, free roam and H. Female-only mode keeps the vanilla male.
- The modified body bundle is served from the plugin folder at runtime; the game's
  `lib/chara/body/body_00.unity3d` stays vanilla, so updates and Steam verification can't break it.

## Install
1. Install **BepInEx 6 IL2CPP** (tested with 6.0.0-be.788) and run the game once.
2. Download the release zip and merge its `BepInEx` folder into the game folder.
3. Start the game. `BepInEx\LogOutput.log` should show `AL Uncensor x.y.z loaded` and, once a character
   loads, `redirecting lib/chara/body/body_00.unity3d -> ...`.

Uninstall: delete `BepInEx\plugins\AL_Uncensor`.

## Configuration
`BepInEx\config\AL_Uncensor.cfg` (created on first run; editable live with ConfigurationManager):

| Entry | Default | What it does |
|---|---|---|
| Enabled | true | master switch |
| Uncensor females / Uncensor males | true | per sex; males off = female-only mode (vanilla penis) |
| Show outside H scenes | true | also show genitals in the maker and free roam |
| No pubic hair on female genitals | true | fade the underhair texture out below the vulva line |
| Keep hair above the vulva | true | keep the mons hair, only remove it from the labia |
| Hair cut line v / Hair fade band | 0.534 / 0.012 | where the mask cuts (underhair-texture V) |
| Vulva pink tint | 0.5 | 0–1, tint inside the slit |
| Penis glans detail / Glans tint strength | true / 0.5 | glans mask and its red tint |
| [Hardmod] Load body bundle from plugin folder | true | the runtime redirect |
| [Hardmod] Body bundle file | (empty) | override; empty = auto from the sex switches |

## Building
See [docs/](docs/) or the Pages site for the technical write-up. Short version:
- Plugin: `dotnet build -c Release -p:GameDir="D:\Games\AmanatsuLocation" src/AL_Uncensor.csproj`
  (references the game's own `dotnet/`, `BepInEx/core` and `BepInEx/interop` assemblies).
- Bundle + data files: `pip install UnityPy numpy scipy trimesh rtree pillow`, then
  `./build_bundle.sh <vanilla body_00.unity3d> <Aicomi hardmod body_00.unity3d>`.

## Credits
Meshes and glans mask: **DilleDing** (Aicomi ACUncensorHardmod). Port, plugin and tooling: fusionpoo & Claude.
Code is MIT; DilleDing's assets in the release packages are his.
