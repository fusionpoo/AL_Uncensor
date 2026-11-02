#!/usr/bin/env bash
# Builds AL_Uncensor.dll against the game's own BepInEx / interop / .NET 6 runtime assemblies.
set -euo pipefail
cd "$(dirname "$0")/src"
G=${GAME_DIR:-/path/to/AmanatsuLocation}
CSC=$(ls /usr/lib/dotnet/sdk/*/Roslyn/bincore/csc.dll | head -1)
OUT=../build; mkdir -p "$OUT"

REFS=()
for f in \
  "$G/dotnet/System.Runtime.dll" "$G/dotnet/System.Private.CoreLib.dll" "$G/dotnet/System.Collections.dll" \
  "$G/dotnet/System.Linq.dll" "$G/dotnet/System.Runtime.InteropServices.dll" "$G/dotnet/netstandard.dll" \
  "$G/dotnet/System.Runtime.Extensions.dll" "$G/dotnet/System.Console.dll" "$G/dotnet/System.Memory.dll" \
  "$G/dotnet/System.Runtime.CompilerServices.Unsafe.dll" "$G/dotnet/System.ObjectModel.dll" \
  "$G/dotnet/System.Threading.dll" "$G/dotnet/System.IO.Compression.dll" "$G/dotnet/System.Runtime.InteropServices.dll" "$G/dotnet/System.Collections.Concurrent.dll" \
  "$G/BepInEx/core/BepInEx.Core.dll" "$G/BepInEx/core/BepInEx.Unity.IL2CPP.dll" "$G/BepInEx/core/BepInEx.Unity.Common.dll" \
  "$G/BepInEx/core/Il2CppInterop.Runtime.dll" "$G/BepInEx/core/Il2CppInterop.Common.dll" "$G/BepInEx/core/0Harmony.dll" \
  "$G/BepInEx/interop/Assembly-CSharp.dll" "$G/BepInEx/interop/Il2Cppmscorlib.dll" "$G/BepInEx/interop/Il2CppSystem.dll" \
  "$G/BepInEx/interop/Il2CppSystem.Core.dll" "$G/BepInEx/interop/UnityEngine.dll" "$G/BepInEx/interop/UnityEngine.CoreModule.dll" \
  "$G/BepInEx/interop/UnityEngine.AssetBundleModule.dll" "$G/BepInEx/interop/UniTask.dll" "$G/BepInEx/interop/R3.dll" \
  "$G/BepInEx/interop/ObservableCollections.dll" "$G/BepInEx/interop/__Generated.dll" "$G/BepInEx/interop/Assembly-CSharp-firstpass.dll" \
  "$G/BepInEx/interop/EPO.dll" "$G/BepInEx/interop/FluidFlow.dll" "$G/BepInEx/interop/MagicaClothV2.dll" \
  "$G/BepInEx/interop/UnityEngine.AnimationModule.dll" "$G/BepInEx/interop/UnityEngine.PhysicsModule.dll" \
  "$G/BepInEx/interop/Unity.Addressables.dll" "$G/BepInEx/interop/Unity.ResourceManager.dll" "$G/BepInEx/interop/ZLinq.dll" ; do
  [ -f "$f" ] && REFS+=("-r:$f")
done

dotnet "$CSC" -nologo -target:library -optimize+ -debug:portable -langversion:10 -nullable:disable \
  -out:"$OUT/AL_Uncensor.dll" "${REFS[@]}" AL_Uncensor.cs
echo "built $OUT/AL_Uncensor.dll ($(stat -c%s "$OUT/AL_Uncensor.dll") bytes)"
