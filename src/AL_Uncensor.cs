// AL_Uncensor — mosaic removal for Amanatsu Location (ILLGAMES, Unity 6 / IL2CPP / BepInEx 6)
//
// How the game censors: the female (mnpa / mnpb) and male (o_dankon / o_dan_f) genital renderers
// wear a dedicated material "cf_m_mnpb_00" on shader "AL/sub/mnpb", which renders the mosaic.
// This plugin swaps that material for the character's *live* skin material (the one the game
// builds at runtime on o_body, shader "AL/skin_body"), so those renderers draw as ordinary skin.
// Geometry is left untouched (vanilla low-poly placeholders) — a later stage can swap meshes.

using System;
using System.Collections.Generic;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using BepInEx.Unity.IL2CPP;
using Character;
using HarmonyLib;
using Il2CppInterop.Runtime;
using Il2CppInterop.Runtime.InteropTypes.Arrays;
using UnityEngine;

namespace AL_Uncensor
{
    [BepInPlugin(GUID, PluginName, Version)]
    public class ALUncensorPlugin : BasePlugin
    {
        public const string GUID = "com.fusionpoo.al_uncensor";
        public const string PluginName = "AL Uncensor";
        public const string Version = "0.9.1";

        internal static ManualLogSource Logger;
        internal static ConfigEntry<bool> Enabled;
        internal static ConfigEntry<bool> FemaleEnabled;
        internal static ConfigEntry<bool> MaleEnabled;
        internal static ConfigEntry<bool> VerboseLog;
        internal static ConfigEntry<bool> ForceShow;
        internal static ConfigEntry<bool> HairMask;
        internal static ConfigEntry<bool> HairKeepMons;
        internal static ConfigEntry<float> HairCutV;
        internal static ConfigEntry<float> HairFadeBand;
        internal static ConfigEntry<bool> PenisDetail;
        internal static ConfigEntry<float> VulvaPink;
        internal static ConfigEntry<float> NearFade;
        internal static ConfigEntry<float> GlansTint;
        internal static ConfigEntry<bool> HardmodFromPlugin;
        internal static ConfigEntry<string> HardmodFile;
        internal static string PluginDir;

        // Material name / shader name used by the game for the mosaic.
        internal const string MosaicMaterialToken = "mnpb";
        internal const string MosaicShaderName = "AL/sub/mnpb";
        internal const string SkinShaderName = "AL/skin_body";

        public override void Load()
        {
            Logger = Log;

            Enabled = Config.Bind("General", "Enabled", true,
                "Master switch. When off the game's mosaic is left alone (takes effect on next character load).");
            FemaleEnabled = Config.Bind("General", "Uncensor females", true,
                "Swap the mosaic material on female characters (mnpa / mnpb, plus futanari parts).");
            MaleEnabled = Config.Bind("General", "Uncensor males", true,
                "Swap the mosaic material on male characters (o_dankon / o_dan_f).");
            VerboseLog = Config.Bind("Debug", "Verbose logging", true,
                "Log every renderer that gets swapped. Turn off once things work.");
            ForceShow = Config.Bind("General", "Show outside H scenes", true,
                "The game hides the genital group (HideMoz) everywhere except H scenes. With this on the plugin clears HideMoz so the maker and normal gameplay show them too (clothing still covers them).");

            HairMask = Config.Bind("General", "No pubic hair on female genitals", true,
                "Give the vulva/anus meshes their own copy of the skin material with the underhair layer removed (the game paints hair right over that area).");

            HairKeepMons = Config.Bind("General", "Keep hair above the vulva", true,
                "Fade the underhair out only below the vulva line instead of removing it from the whole patch (avoids a hard hair cut-off at the patch edge).");
            HairCutV = Config.Bind("General", "Hair cut line v", 0.534f,
                new ConfigDescription("Texture row (0..1) below which the underhair is faded out on the genital patch. Labia sit at ~0.52-0.53, mons at 0.534-0.556.", new AcceptableValueRange<float>(0.45f, 0.65f)));
            NearFade = Config.Bind("Experimental", "Body _DistanceCutoff override", -1f,
                new ConfigDescription("The body shader dithers skin away when the camera gets very close (vanilla 0.3), which shows the room through the crotch in close-ups. " +
                                      "-1 (default) = leave the vanilla value (0.3). Experimental: other values are written to the body material's _DistanceCutoff. Too small hides the arm/leg mesh.", new AcceptableValueRange<float>(-1f, 1f)));
            VulvaPink = Config.Bind("General", "Vulva pink tint", 0.5f,
                new ConfigDescription("Pink tint inside the labia (painted into the body's detail mask; needs labia_mask.r next to the plugin DLL). 0 = off.", new AcceptableValueRange<float>(0f, 1f)));
            PenisDetail = Config.Bind("General", "Penis glans detail", true,
                "Use the glans detail mask on the ported penis (needs cm_dankon_00_det.rg next to the plugin DLL).");
            GlansTint = Config.Bind("General", "Glans tint strength", 0.5f,
                new ConfigDescription("How strongly the glans is tinted red (0 = plain skin).", new AcceptableValueRange<float>(0f, 1f)));
            HairFadeBand = Config.Bind("General", "Hair fade band", 0.012f,
                new ConfigDescription("Height of the fade (in UV v) just below the cut line.", new AcceptableValueRange<float>(0.002f, 0.05f)));

            HardmodFromPlugin = Config.Bind("Hardmod", "Load body bundle from plugin folder", true,
                "Redirect the game's lib/chara/body/body_00.unity3d load to the file next to this DLL, so the game files stay untouched. " +
                "If the file is missing the game's own bundle is used (only the material swap then applies).");
            HardmodFile = Config.Bind("Hardmod", "Body bundle file", "",
                "Override: file name (relative to the plugin folder) or absolute path of the body bundle to serve. " +
                "Leave empty to pick automatically from the 'Uncensor females' / 'Uncensor males' switches: " +
                "both on -> body_00.unity3d, females only -> body_00.female.unity3d (vanilla penis kept), males only -> body_00.male.unity3d if present, else body_00.unity3d.");
            PluginDir = System.IO.Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);

            var harmony = new Harmony(GUID);
            harmony.PatchAll(typeof(Hooks));
            BundleRedirect.Install(harmony);

            int patched = 0;
            foreach (var _ in harmony.GetPatchedMethods()) patched++;
            Log.LogInfo($"{PluginName} {Version} loaded. {patched} game method(s) hooked.");
        }
    }

    // Serves the modified body bundle from the plugin folder instead of lib/chara/body/body_00.unity3d.
    // Every public AssetBundle.LoadFromFile* overload plus the internal funnels are hooked; a prefix that
    // recognises the vanilla path re-issues the call with our path (guarded against re-entry) and skips
    // the original.
    internal static class BundleRedirect
    {
        internal const string TargetSuffix = "lib/chara/body/body_00.unity3d";
        [ThreadStatic] private static bool _inRedirect;
        private static int _logged;
        private static bool _announced;

        internal static string ResolveHardmod()
        {
            if (!ALUncensorPlugin.HardmodFromPlugin.Value) return null;
            var f = ALUncensorPlugin.HardmodFile.Value;
            if (!string.IsNullOrEmpty(f))
            {
                if (!System.IO.Path.IsPathRooted(f)) f = System.IO.Path.Combine(ALUncensorPlugin.PluginDir, f);
                return System.IO.File.Exists(f) ? f : null;
            }
            bool fem = ALUncensorPlugin.FemaleEnabled.Value, male = ALUncensorPlugin.MaleEnabled.Value;
            if (!fem && !male) return null;                                   // nothing to uncensor: serve the vanilla bundle
            var order = fem && male ? new[] { "body_00.unity3d" }
                      : fem ? new[] { "body_00.female.unity3d", "body_00.unity3d" }
                            : new[] { "body_00.male.unity3d", "body_00.unity3d" };
            foreach (var name in order)
            {
                var p = System.IO.Path.Combine(ALUncensorPlugin.PluginDir, name);
                if (System.IO.File.Exists(p)) return p;
            }
            return null;
        }

        internal static string Redirect(string path)
        {
            if (_inRedirect || string.IsNullOrEmpty(path)) return null;
            var norm = path.Replace('\\', '/');
            if (ALUncensorPlugin.VerboseLog.Value && _logged < 40) { _logged++; ALUncensorPlugin.Logger.LogInfo($"    [bundle] load {norm}"); }
            if (!norm.EndsWith(TargetSuffix, StringComparison.OrdinalIgnoreCase)) return null;
            var hm = ResolveHardmod();
            if (hm == null)
            {
                if (!_announced) { _announced = true; ALUncensorPlugin.Logger.LogWarning($"hardmod bundle not found next to the plugin ('{ALUncensorPlugin.HardmodFile.Value}'); using the game's body_00.unity3d"); }
                return null;
            }
            if (!_announced) { _announced = true; ALUncensorPlugin.Logger.LogInfo($"redirecting {TargetSuffix} -> {hm}"); }
            return hm;
        }

        internal static void Install(Harmony harmony)
        {
            var t = typeof(AssetBundle);
            var pre = new HarmonyMethod(typeof(BundleRedirect), nameof(LoadFromFile_Prefix));
            var preA = new HarmonyMethod(typeof(BundleRedirect), nameof(LoadFromFileAsync_Prefix));
            int n = 0;
            foreach (var (name, args, hook) in new[] {
                ("LoadFromFile", new[] { typeof(string) }, pre),
                ("LoadFromFile", new[] { typeof(string), typeof(uint) }, pre),
                ("LoadFromFile", new[] { typeof(string), typeof(uint), typeof(ulong) }, pre),
                ("LoadFromFile_Internal", new[] { typeof(string), typeof(uint), typeof(ulong) }, pre),
                ("LoadFromFileAsync", new[] { typeof(string) }, preA),
                ("LoadFromFileAsync", new[] { typeof(string), typeof(uint) }, preA),
                ("LoadFromFileAsync", new[] { typeof(string), typeof(uint), typeof(ulong) }, preA),
                ("LoadFromFileAsync_Internal", new[] { typeof(string), typeof(uint), typeof(ulong) }, preA) })
            {
                try
                {
                    var m = AccessTools.Method(t, name, args);
                    if (m == null) { ALUncensorPlugin.Logger.LogDebug($"AssetBundle.{name}({args.Length}) not found"); continue; }
                    harmony.Patch(m, prefix: hook); n++;
                }
                catch (Exception e) { ALUncensorPlugin.Logger.LogWarning($"could not hook AssetBundle.{name}({args.Length}): {e.Message}"); }
            }
            ALUncensorPlugin.Logger.LogInfo($"bundle redirect: {n} AssetBundle load method(s) hooked; hardmod file {(ResolveHardmod() ?? "not found")}");
        }

        // __0 = path, __1 = crc (optional), __2 = offset (optional)
        private static bool LoadFromFile_Prefix(ref AssetBundle __result, object[] __args)
        {
            try
            {
                var np = Redirect(__args.Length > 0 ? __args[0] as string : null); if (np == null) return true;
                uint crc = __args.Length > 1 && __args[1] is uint c ? c : 0u; ulong off = __args.Length > 2 && __args[2] is ulong o ? o : 0ul;
                _inRedirect = true;
                try { __result = AssetBundle.LoadFromFile(np, crc, off); } finally { _inRedirect = false; }
                return false;
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogWarning($"bundle redirect failed: {e.Message}"); _inRedirect = false; return true; }
        }

        private static bool LoadFromFileAsync_Prefix(ref AssetBundleCreateRequest __result, object[] __args)
        {
            try
            {
                var np = Redirect(__args.Length > 0 ? __args[0] as string : null); if (np == null) return true;
                uint crc = __args.Length > 1 && __args[1] is uint c ? c : 0u; ulong off = __args.Length > 2 && __args[2] is ulong o ? o : 0ul;
                _inRedirect = true;
                try { __result = AssetBundle.LoadFromFileAsync(np, crc, off); } finally { _inRedirect = false; }
                return false;
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogWarning($"bundle redirect (async) failed: {e.Message}"); _inRedirect = false; return true; }
        }
    }

    internal static class Hooks
    {
        // The live skin material is created here (per body renderer). Fires on initial load and
        // on every skin reload (maker colour changes, coordinate reloads, etc.).
        [HarmonyPostfix]
        [HarmonyPatch(typeof(HumanBody), nameof(HumanBody.SetBodyBaseMaterial))]
        private static void HumanBody_SetBodyBaseMaterial_Postfix(HumanBody __instance)
        {
            try
            {
                var human = __instance._human;
                if (human != null) Uncensor.Apply(human, "HumanBody.SetBodyBaseMaterial");
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogError($"SetBodyBaseMaterial hook failed: {e}"); }
        }

        // Belt and braces: after a full character load.
        [HarmonyPostfix]
        [HarmonyPatch(typeof(Human), nameof(Human.Load))]
        private static void Human_Load_Postfix(Human __instance)
        {
            try { Uncensor.Apply(__instance, "Human.Load"); }
            catch (Exception e) { ALUncensorPlugin.Logger.LogError($"Human.Load hook failed: {e}"); }
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(Human), nameof(Human.ReloadSkin))]
        private static void Human_ReloadSkin_Postfix(Human __instance)
        {
            try { Uncensor.Apply(__instance, "Human.ReloadSkin"); }
            catch (Exception e) { ALUncensorPlugin.Logger.LogError($"Human.ReloadSkin hook failed: {e}"); }
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(Human), nameof(Human.Reload), new Type[0])]
        private static void Human_Reload_Postfix(Human __instance)
        {
            try { Uncensor.Apply(__instance, "Human.Reload"); }
            catch (Exception e) { ALUncensorPlugin.Logger.LogError($"Human.Reload hook failed: {e}"); }
        }

        // The game sets Human.HideMoz = true outside H scenes and UpdateVisible then deactivates the
        // n_mnpb / n_dankon group nodes. Clearing the flag right before UpdateVisible runs makes the
        // game's own logic show them (it still hides them under clothing).
        [HarmonyPrefix]
        [HarmonyPatch(typeof(HumanBody), nameof(HumanBody.UpdateVisible))]
        private static void HumanBody_UpdateVisible_Prefix(HumanBody __instance)
        {
            try
            {
                if (!ALUncensorPlugin.Enabled.Value || !ALUncensorPlugin.ForceShow.Value) return;
                var human = __instance._human;
                if (human == null || human.Disposed) return;
                if (!Uncensor.SexAllowed(human)) return;
                if (human.HideMoz) human.HideMoz = false;
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogDebug($"HideMoz clear failed: {e.Message}"); }
        }

        [HarmonyPrefix]
        [HarmonyPatch(typeof(Human), nameof(Human.UpdateVisible))]
        private static void Human_UpdateVisible_Prefix(Human __instance)
        {
            try
            {
                if (!ALUncensorPlugin.Enabled.Value || !ALUncensorPlugin.ForceShow.Value) return;
                if (__instance == null || __instance.Disposed) return;
                if (!Uncensor.SexAllowed(__instance)) return;
                if (__instance.HideMoz) __instance.HideMoz = false;
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogDebug($"HideMoz clear failed: {e.Message}"); }
        }

        // Keep the patch material clones in sync with the live skin material (colour, wet, sweat...).
        [HarmonyPostfix]
        [HarmonyPatch(typeof(HumanBody), nameof(HumanBody.LateUpdate))]
        private static void HumanBody_LateUpdate_Postfix(HumanBody __instance)
        {
            try
            {
                var human = __instance._human;
                if (human != null) Uncensor.SyncClones(human);
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogDebug($"LateUpdate sync failed: {e.Message}"); }
        }

        // Cheap re-check whenever the game re-evaluates visibility (clothing state changes etc.).
        // Only touches renderers we already found; no hierarchy scan.
        [HarmonyPostfix]
        [HarmonyPatch(typeof(HumanBody), nameof(HumanBody.UpdateVisible))]
        private static void HumanBody_UpdateVisible_Postfix(HumanBody __instance)
        {
            try
            {
                var human = __instance._human;
                if (human != null) Uncensor.Reapply(human);
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogError($"UpdateVisible hook failed: {e}"); }
        }
    }

    internal static class Uncensor
    {
        private sealed class Entry
        {
            public Renderer Skin;                 // the live body renderer we borrow the material from
            public List<Renderer> Targets = new List<Renderer>();
            public Dictionary<int, Material> Clones = new Dictionary<int, Material>();   // renderer id -> patch material
            public Dictionary<int, CloneKind> Kinds = new Dictionary<int, CloneKind>();
            public Texture2D Tone; public Color32 ToneColor; public bool ToneValid; public int ToneFrame = -1000;
        }

        internal const string PatchMaterialName = "al_uncensor_patch";
        internal const string UnderHairProp = "_Under_hair_texture";
        private static Texture2D _transparent;
        private static Texture2D Transparent()
        {
            if (_transparent != null) return _transparent;
            var t = new Texture2D(4, 4, TextureFormat.RGBA32, false);
            for (int y = 0; y < 4; y++) for (int x = 0; x < 4; x++) t.SetPixel(x, y, new Color(1f, 1f, 1f, 0f));
            t.Apply(); t.name = "al_uncensor_nohair"; t.hideFlags = HideFlags.HideAndDontSave;
            _transparent = t; _ours.Add(t.GetInstanceID()); return t;
        }

        private static readonly Dictionary<int, Texture2D> _hairMasked = new Dictionary<int, Texture2D>();
        private static float _hairMaskedCutV = -1f;
        private static readonly HashSet<int> _ours = new HashSet<int>();                    // textures this plugin created
        private static readonly Dictionary<int, Texture> _origHair = new Dictionary<int, Texture>(); // skin material id -> game's own underhair

        // The game's underhair texture for this skin material, remembered across our own replacements
        // (the merged hardmod body gets the masked texture set directly on the body material).
        private static Texture OriginalOf(Material skinMat, string prop)
        {
            Texture cur = null; try { cur = skinMat.GetTexture(prop); } catch { }
            int key = skinMat.GetInstanceID() * 31 + prop.GetHashCode();
            if (cur != null && !_ours.Contains(cur.GetInstanceID())) { _origHair[key] = cur; return cur; }
            if (_origHair.TryGetValue(key, out var o) && o != null) return o;
            return null;
        }
        private static Texture OriginalHair(Material skinMat) => OriginalOf(skinMat, UnderHairProp);

        private static Texture2D ReadableCopy(Texture src, int w, int h)
        {
            var rt = RenderTexture.GetTemporary(w, h, 0, RenderTextureFormat.ARGB32);
            var prev = RenderTexture.active;
            if (src != null) Graphics.Blit(src, rt);
            else { RenderTexture.active = rt; GL.Clear(true, true, new Color(0, 0, 0, 0)); }
            RenderTexture.active = rt;
            var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
            tex.ReadPixels(new Rect(0, 0, w, h), 0, 0, false);
            RenderTexture.active = prev; RenderTexture.ReleaseTemporary(rt);
            return tex;
        }

        // ---- pink tint inside the labia: painted into channel R of the body's _Detail_mask_02 (tinted by _Detail_color_02)
        private struct LabiaMask { public float u0, v0, u1, v1; public int w, h; public byte[] a; }
        private static LabiaMask? _labia; private static bool _labiaTried;
        private static LabiaMask? LoadLabiaMask()
        {
            if (_labia != null || _labiaTried) return _labia;
            _labiaTried = true;
            try
            {
                var dir = System.IO.Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);
                var path = System.IO.Path.Combine(dir, "labia_mask.r");
                if (!System.IO.File.Exists(path)) { ALUncensorPlugin.Logger.LogWarning($"labia mask not found: {path}"); return null; }
                var raw = System.IO.File.ReadAllBytes(path);
                if (raw.Length < 28 || raw[0] != (byte)'A' || raw[1] != (byte)'L' || raw[2] != (byte)'L' || raw[3] != (byte)'M') return null;
                var m = new LabiaMask { u0 = BitConverter.ToSingle(raw, 4), v0 = BitConverter.ToSingle(raw, 8), u1 = BitConverter.ToSingle(raw, 12), v1 = BitConverter.ToSingle(raw, 16),
                                        w = BitConverter.ToInt32(raw, 20), h = BitConverter.ToInt32(raw, 24) };
                m.a = new byte[m.w * m.h]; Buffer.BlockCopy(raw, 28, m.a, 0, m.a.Length);
                _labia = m; ALUncensorPlugin.Logger.LogInfo($"labia mask loaded ({m.w}x{m.h}, uv {m.u0:F3}-{m.u1:F3} x {m.v0:F3}-{m.v1:F3})");
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogWarning($"labia mask failed: {e.Message}"); }
            return _labia;
        }

        private static readonly Dictionary<long, Texture2D> _pinkMasked = new Dictionary<long, Texture2D>();
        private static Texture PinkDetailFor(Material skinMat)
        {
            var lm = LoadLabiaMask(); if (lm == null) return null;
            float strength = ALUncensorPlugin.VulvaPink.Value; if (strength <= 0f) return null;
            Texture src = OriginalOf(skinMat, "_Detail_mask_02");
            long key = ((long)(src != null ? src.GetInstanceID() : 0) << 16) ^ (long)Mathf.RoundToInt(strength * 1000f);
            if (_pinkMasked.TryGetValue(key, out var cached) && cached != null) return cached;
            try
            {
                int w = src != null ? src.width : 1024, h = src != null ? src.height : 1024;
                var tex = ReadableCopy(src, w, h);
                var px = tex.GetPixels32(); var m = lm.Value;
                int x0 = Mathf.Clamp((int)(m.u0 * w), 0, w - 1), x1 = Mathf.Clamp((int)(m.u1 * w) + 1, 0, w), y0 = Mathf.Clamp((int)(m.v0 * h), 0, h - 1), y1 = Mathf.Clamp((int)(m.v1 * h) + 1, 0, h);
                for (int y = y0; y < y1; y++)
                {
                    float fv = ((y + 0.5f) / h - m.v0) / (m.v1 - m.v0) * m.h - 0.5f;
                    for (int x = x0; x < x1; x++)
                    {
                        float fu = ((x + 0.5f) / w - m.u0) / (m.u1 - m.u0) * m.w - 0.5f;
                        int iu = Mathf.Clamp((int)fu, 0, m.w - 2), iv = Mathf.Clamp((int)fv, 0, m.h - 2);
                        float du = Mathf.Clamp01(fu - iu), dv = Mathf.Clamp01(fv - iv);
                        float a = (m.a[iv * m.w + iu] * (1 - du) + m.a[iv * m.w + iu + 1] * du) * (1 - dv) + (m.a[(iv + 1) * m.w + iu] * (1 - du) + m.a[(iv + 1) * m.w + iu + 1] * du) * dv;
                        int add = Mathf.RoundToInt(a * strength);
                        if (add <= 0) continue;
                        int i = y * w + x; var c = px[i];
                        c.r = (byte)Mathf.Max(c.r, add); px[i] = c;
                    }
                }
                tex.SetPixels32(px); tex.Apply(false, false);
                try { if (src != null) { tex.wrapMode = src.wrapMode; tex.filterMode = src.filterMode; } } catch { }
                tex.name = "al_uncensor_detail_pink"; tex.hideFlags = HideFlags.HideAndDontSave;
                _pinkMasked[key] = tex; _ours.Add(tex.GetInstanceID());
                if (ALUncensorPlugin.VerboseLog.Value) ALUncensorPlugin.Logger.LogInfo($"    built pink detail mask from '{(src != null ? src.name : "none")}' ({w}x{h}), strength {strength}");
                return tex;
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogWarning($"pink detail mask failed: {e.Message}"); return null; }
        }

        // Copy of the character's underhair texture with the alpha faded out below the vulva line.
        private static Texture HairFor(Material skinMat)
        {
            Texture src = OriginalHair(skinMat);
            if (!ALUncensorPlugin.HairKeepMons.Value) return Transparent();
            if (src == null) return Transparent();
            float cut = ALUncensorPlugin.HairCutV.Value; float band = ALUncensorPlugin.HairFadeBand.Value;
            float key = cut * 1000f + band;
            if (_hairMaskedCutV != key) { _hairMasked.Clear(); _hairMaskedCutV = key; }
            int id = src.GetInstanceID();
            if (_hairMasked.TryGetValue(id, out var cached) && cached != null) return cached;
            try
            {
                int w = src.width, h = src.height;
                var rt = RenderTexture.GetTemporary(w, h, 0, RenderTextureFormat.ARGB32);
                var prev = RenderTexture.active;
                Graphics.Blit(src, rt);
                RenderTexture.active = rt;
                var tex = new Texture2D(w, h, TextureFormat.RGBA32, false);
                tex.ReadPixels(new Rect(0, 0, w, h), 0, 0, false);
                RenderTexture.active = prev;
                RenderTexture.ReleaseTemporary(rt);
                var px = tex.GetPixels32();
                for (int y = 0; y < h; y++)
                {
                    float v = (y + 0.5f) / h;                       // row 0 = bottom = v 0
                    float f = Mathf.Clamp01((v - (cut - band)) / band); // 0 below the line, 1 above
                    f = f * f * (3f - 2f * f);
                    if (f >= 1f) continue;
                    for (int x = 0; x < w; x++)
                    {
                        int i = y * w + x; var c = px[i];
                        c.a = (byte)Mathf.RoundToInt(c.a * f); px[i] = c;
                    }
                }
                tex.SetPixels32(px); tex.Apply(false, false);
                tex.name = "al_uncensor_hair_masked"; tex.hideFlags = HideFlags.HideAndDontSave;
                _hairMasked[id] = tex; _ours.Add(tex.GetInstanceID());
                if (ALUncensorPlugin.VerboseLog.Value)
                    ALUncensorPlugin.Logger.LogInfo($"    built masked underhair from '{src.name}' ({w}x{h}), cut at v={cut}");
                return tex;
            }
            catch (Exception e)
            {
                ALUncensorPlugin.Logger.LogWarning($"masked underhair failed ({e.Message}); using transparent");
                return Transparent();
            }
        }

        private enum CloneKind { None, HairPatch, Dankon, DanF }

        private static CloneKind KindFor(Renderer r, Human human)
        {
            var n = r.name;
            if (n == "o_dankon") return CloneKind.Dankon;           // own UV layout: needs its own material
            if (n == "o_dan_f") return CloneKind.DanF;
            if (!ALUncensorPlugin.HairMask.Value || human.Sex == 0) return CloneKind.None;
            return (n == "mnpa" || n == "mnpb") ? CloneKind.HairPatch : CloneKind.None;
        }

        private static Material CloneFor(Entry entry, Renderer r, Material skinMat, CloneKind kind)
        {
            int id = r.GetInstanceID();
            if (entry.Clones.TryGetValue(id, out var m) && m != null) return m;
            m = new Material(skinMat); m.hideFlags = HideFlags.HideAndDontSave;
            m.name = kind == CloneKind.HairPatch ? PatchMaterialName : (kind == CloneKind.Dankon ? "al_uncensor_dankon" : "al_uncensor_dan_f");
            if (kind != CloneKind.HairPatch && !entry.ToneValid) { entry.ToneFrame = Time.frameCount; SampleTone(entry, skinMat); }
            ApplyOverrides(entry, m, kind, skinMat);
            entry.Clones[id] = m; entry.Kinds[id] = kind; return m;
        }

        private static void ApplyOverrides(Entry entry, Material m, CloneKind kind, Material skinMat)
        {
            ApplyFade(m);
            if (kind == CloneKind.HairPatch) { m.SetTexture(UnderHairProp, HairFor(skinMat)); return; }
            // Penis: DilleDing's mesh has its own 0..1 UV layout, so every body-UV texture must go and the
            // main colour becomes a flat sample of this character's generated skin texture.
            m.SetTexture("_Create_main_texture", entry.Tone != null ? entry.Tone : (Texture)Transparent());
            foreach (var t in BodySpaceTextures) m.SetTexture(t, null);
            bool det = kind == CloneKind.Dankon && ALUncensorPlugin.PenisDetail.Value && DankonDet() != null;
            m.SetTexture("_Detail_mask_02", det ? DankonDet() : null);
            if (det) m.SetColor("_Detail_color_02", new Color(1f, 0.447f, 0.447f, ALUncensorPlugin.GlansTint.Value));
        }

        private static void ApplyFade(Material m)
        {
            float v = ALUncensorPlugin.NearFade.Value;
            if (v < 0f) return;
            try
            {
                // never touch _Dither: zeroing it makes the shader discard the whole mesh (arms/legs vanished)
                m.SetFloat("_DistanceCutoff", v <= 0f ? 0.001f : v);
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogDebug($"fade: {e.Message}"); }
        }

        private static readonly string[] BodySpaceTextures = {
            "_Detail_mask_01", "_TexEX", "_Normal_map", "_Nip", UnderHairProp, "_Cloth_alpha", "_Cloth_alpha_bot",
            "_Create_dent_texture", "_shine_texture", "_FluidTex" };

        // ---- glans detail mask, shipped as raw "ALDT"+w+h header followed by R,G bytes (bottom row first) next to the DLL
        private static Texture2D _dankonDet; private static bool _dankonDetTried;
        private static Texture2D DankonDet()
        {
            if (_dankonDet != null || _dankonDetTried) return _dankonDet;
            _dankonDetTried = true;
            try
            {
                var dir = System.IO.Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);
                var path = System.IO.Path.Combine(dir, "cm_dankon_00_det.rg");
                if (!System.IO.File.Exists(path)) { ALUncensorPlugin.Logger.LogWarning($"penis detail mask not found: {path}"); return null; }
                byte[] raw = System.IO.File.ReadAllBytes(path);
                if (raw.Length < 12 || raw[0] != (byte)'A' || raw[1] != (byte)'L' || raw[2] != (byte)'D' || raw[3] != (byte)'T') { ALUncensorPlugin.Logger.LogWarning("penis detail mask: bad header"); return null; }
                int w = BitConverter.ToInt32(raw, 4), h = BitConverter.ToInt32(raw, 8);
                // LoadRawTextureData on a mipmapped texture wants every mip level, so build the chain here (box filter)
                var levels = new List<byte[]>(); int lw = w, lh = h;
                var cur = new byte[w * h * 4];
                for (int i = 0, j = 12, k = 0; i < w * h; i++, j += 2, k += 4) { cur[k] = raw[j]; cur[k + 1] = raw[j + 1]; cur[k + 2] = 0; cur[k + 3] = 255; }
                levels.Add(cur); int total = cur.Length;
                while (lw > 1 || lh > 1)
                {
                    int nw = Math.Max(1, lw / 2), nh = Math.Max(1, lh / 2); var nxt = new byte[nw * nh * 4];
                    for (int y = 0; y < nh; y++) for (int x = 0; x < nw; x++)
                    {
                        int x0 = Math.Min(x * 2, lw - 1), x1 = Math.Min(x * 2 + 1, lw - 1), y0 = Math.Min(y * 2, lh - 1), y1 = Math.Min(y * 2 + 1, lh - 1);
                        for (int c = 0; c < 4; c++)
                            nxt[(y * nw + x) * 4 + c] = (byte)((cur[(y0 * lw + x0) * 4 + c] + cur[(y0 * lw + x1) * 4 + c] + cur[(y1 * lw + x0) * 4 + c] + cur[(y1 * lw + x1) * 4 + c] + 2) / 4);
                    }
                    levels.Add(nxt); total += nxt.Length; cur = nxt; lw = nw; lh = nh;
                }
                var all = new byte[total]; int off = 0;
                foreach (var lv in levels) { Buffer.BlockCopy(lv, 0, all, off, lv.Length); off += lv.Length; }
                var tex = new Texture2D(w, h, TextureFormat.RGBA32, true);
                tex.LoadRawTextureData((Il2CppStructArray<byte>)all);
                tex.Apply(false, false); tex.wrapMode = TextureWrapMode.Clamp;
                tex.name = "al_uncensor_dankon_det"; tex.hideFlags = HideFlags.HideAndDontSave;
                _dankonDet = tex;
                ALUncensorPlugin.Logger.LogInfo($"penis detail mask loaded ({w}x{h})");
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogWarning($"penis detail mask failed: {e.Message}"); }
            return _dankonDet;
        }

        // ---- flat skin-tone texture sampled from the character's generated body texture (a plain-skin spot)
        private static Texture2D _probe;
        private static bool SampleTone(Entry entry, Material skinMat)
        {
            Texture src = null; try { src = skinMat.GetTexture("_Create_main_texture"); } catch { }
            if (src == null || src.width < 16) return false;
            try
            {
                if (_probe == null) { _probe = new Texture2D(8, 8, TextureFormat.RGBA32, false); _probe.hideFlags = HideFlags.HideAndDontSave; }
                var rt = src.TryCast<RenderTexture>(); RenderTexture tmp = null;
                if (rt == null) { tmp = RenderTexture.GetTemporary(src.width, src.height, 0, RenderTextureFormat.ARGB32); Graphics.Blit(src, tmp); rt = tmp; }
                var prev = RenderTexture.active; RenderTexture.active = rt;
                int x = Mathf.Clamp((int)(0.65f * rt.width) - 4, 0, rt.width - 8), y = Mathf.Clamp((int)(0.195f * rt.height) - 4, 0, rt.height - 8);
                _probe.ReadPixels(new Rect(x, y, 8, 8), 0, 0, false);
                RenderTexture.active = prev; if (tmp != null) RenderTexture.ReleaseTemporary(tmp);
                var px = _probe.GetPixels32(); long r = 0, g = 0, b = 0; int n = 0;
                foreach (var c in px) { r += c.r; g += c.g; b += c.b; n++; }
                if (n == 0) return false;
                var avg = new Color32((byte)(r / n), (byte)(g / n), (byte)(b / n), 255);
                if (entry.Tone == null)
                {
                    entry.Tone = new Texture2D(4, 4, TextureFormat.RGBA32, false); entry.Tone.name = "al_uncensor_skin_tone"; entry.Tone.hideFlags = HideFlags.HideAndDontSave;
                }
                if (entry.ToneColor.r != avg.r || entry.ToneColor.g != avg.g || entry.ToneColor.b != avg.b || !entry.ToneValid)
                {
                    var fill = new Il2CppStructArray<Color32>(16); for (int i = 0; i < 16; i++) fill[i] = avg;
                    entry.Tone.SetPixels32(fill); entry.Tone.Apply(false, false);
                    entry.ToneColor = avg; entry.ToneValid = true;
                    if (ALUncensorPlugin.VerboseLog.Value) ALUncensorPlugin.Logger.LogInfo($"    skin tone sampled: ({avg.r},{avg.g},{avg.b}) from '{src.name}' {src.width}x{src.height}");
                }
                return true;
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogDebug($"tone sample: {e.Message}"); return false; }
        }

        // Female body material: the vulva/anus geometry now lives inside the body meshes (v13 hardmod), so the
        // pubic-hair mask has to be on the body material itself. Harmless for the older overlay bundle.
        private static void ApplyHairToSkin(Entry entry, Human human)
        {
            var skinMat = entry.Skin != null ? entry.Skin.sharedMaterial : null; if (skinMat == null) return;
            ApplyFade(skinMat);
            if (human.Sex == 0) return;
            try
            {
                var pink = PinkDetailFor(skinMat);
                if (pink != null)
                {
                    Texture curd = null; try { curd = skinMat.GetTexture("_Detail_mask_02"); } catch { }
                    if (curd == null || curd.GetInstanceID() != pink.GetInstanceID()) skinMat.SetTexture("_Detail_mask_02", pink);
                }
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogDebug($"pink: {e.Message}"); }
            if (!ALUncensorPlugin.HairMask.Value) return;
            try
            {
                var want = HairFor(skinMat);
                Texture cur = null; try { cur = skinMat.GetTexture(UnderHairProp); } catch { }
                if (cur == null || cur.GetInstanceID() != want.GetInstanceID()) skinMat.SetTexture(UnderHairProp, want);
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogDebug($"skin hair: {e.Message}"); }
        }

        public static void SyncClones(Human human)
        {
            if (!ALUncensorPlugin.Enabled.Value || human == null || human.Disposed) return;
            var root = RootOf(human); if (root == null) return;
            if (!_cache.TryGetValue(root.GetInstanceID(), out var entry) || entry.Skin == null) return;
            var skinMat = entry.Skin.sharedMaterial; if (skinMat == null) return;
            ApplyHairToSkin(entry, human);
            if (entry.Clones.Count == 0) return;
            bool needTone = false;
            foreach (var kv in entry.Kinds) if (kv.Value == CloneKind.Dankon || kv.Value == CloneKind.DanF) needTone = true;
            int frame = Time.frameCount;
            if (needTone && (!entry.ToneValid || frame - entry.ToneFrame > 30)) { entry.ToneFrame = frame; SampleTone(entry, skinMat); }
            foreach (var kv in entry.Clones)
            {
                var m = kv.Value; if (m == null) continue;
                try
                {
                    m.CopyPropertiesFromMaterial(skinMat);
                    ApplyOverrides(entry, m, entry.Kinds.TryGetValue(kv.Key, out var k) ? k : CloneKind.HairPatch, skinMat);
                }
                catch (Exception e) { ALUncensorPlugin.Logger.LogDebug($"clone sync: {e.Message}"); }
            }
        }

        // keyed by the Human's root GameObject instance id
        private static readonly Dictionary<int, Entry> _cache = new Dictionary<int, Entry>();

        internal static bool SexAllowed(Human human)
        {
            // Sex: 0 = male, 1 = female (ILLGAMES convention)
            bool isFemale = human.Sex != 0;
            return isFemale ? ALUncensorPlugin.FemaleEnabled.Value : ALUncensorPlugin.MaleEnabled.Value;
        }

        private static GameObject RootOf(Human human)
        {
            var go = human.ObjTop;
            if (go == null) go = human.GameObject;
            return go;
        }

        private static bool IsMosaicMaterial(Material m)
        {
            if (m == null) return false;
            var shader = m.shader;
            if (shader != null && shader.name == ALUncensorPlugin.MosaicShaderName) return true;
            return m.name.Contains(ALUncensorPlugin.MosaicMaterialToken);
        }

        private static Renderer FindSkinRenderer(Human human, GameObject root)
        {
            // Preferred: the game's own reference to o_body.
            try
            {
                var objBody = human.GetRefObject(Table.RefObjKey.ObjBody);
                if (objBody != null)
                {
                    var r = objBody.GetComponent<Renderer>();
                    if (r != null && r.sharedMaterial != null && r.sharedMaterial.shader != null &&
                        r.sharedMaterial.shader.name == ALUncensorPlugin.SkinShaderName)
                        return r;
                }
            }
            catch (Exception e) { ALUncensorPlugin.Logger.LogDebug($"GetRefObject(ObjBody) failed: {e.Message}"); }

            // Fallback: any renderer named o_body using the skin shader.
            var all = root.GetComponentsInChildren(Il2CppType.Of<SkinnedMeshRenderer>(), true);
            foreach (var c in all)
            {
                var smr = c.TryCast<SkinnedMeshRenderer>();
                if (smr == null) continue;
                var m = smr.sharedMaterial;
                if (m == null || m.shader == null) continue;
                if (smr.name == "o_body" && m.shader.name == ALUncensorPlugin.SkinShaderName) return smr;
            }
            return null;
        }

        public static void Apply(Human human, string reason)
        {
            if (!ALUncensorPlugin.Enabled.Value) return;
            if (human == null || human.Disposed) return;
            if (!SexAllowed(human)) return;

            var root = RootOf(human);
            if (root == null) return;
            int key = root.GetInstanceID();

            var skin = FindSkinRenderer(human, root);
            if (skin == null)
            {
                if (ALUncensorPlugin.VerboseLog.Value)
                    ALUncensorPlugin.Logger.LogWarning($"[{reason}] {human.Name}: no live skin material yet (o_body not on {ALUncensorPlugin.SkinShaderName}); will retry on next hook.");
                return;
            }

            var entry = new Entry { Skin = skin };
            var comps = root.GetComponentsInChildren(Il2CppType.Of<SkinnedMeshRenderer>(), true);
            foreach (var c in comps)
            {
                var smr = c.TryCast<SkinnedMeshRenderer>();
                if (smr == null) continue;
                if (IsMosaicMaterial(smr.sharedMaterial))
                    entry.Targets.Add(smr);
            }

            // Renderers we swapped on a previous pass no longer carry the mosaic material; keep them.
            if (_cache.TryGetValue(key, out var old))
            {
                foreach (var r in old.Targets)
                    if (r != null && !entry.Targets.Contains(r)) entry.Targets.Add(r);
                entry.Clones = old.Clones; entry.Kinds = old.Kinds; entry.Tone = old.Tone; entry.ToneColor = old.ToneColor; entry.ToneValid = old.ToneValid;
            }
            _cache[key] = entry;

            int swapped = Swap(entry, human, reason);
            if (ALUncensorPlugin.VerboseLog.Value)
                ALUncensorPlugin.Logger.LogInfo($"[{reason}] {human.Name} (sex={human.Sex}): {entry.Targets.Count} mosaic renderer(s) tracked, {swapped} swapped to '{skin.sharedMaterial.name}'.");
        }

        public static void Reapply(Human human)
        {
            if (!ALUncensorPlugin.Enabled.Value) return;
            if (human == null || human.Disposed) return;
            var root = RootOf(human);
            if (root == null) return;
            if (!_cache.TryGetValue(root.GetInstanceID(), out var entry)) return;
            if (entry.Skin == null) { _cache.Remove(root.GetInstanceID()); return; }
            Swap(entry, human, "UpdateVisible");
        }

        private static readonly Dictionary<int, string> _lastState = new Dictionary<int, string>();

        private static bool KokanCovered(Human human)
        {
            try { var c = human.Cloth; return c != null && c.IsHideKokan(); } catch { return false; }
        }

        private static void ForceShowAndDiagnose(Entry entry, Human human, string reason)
        {
            bool covered = KokanCovered(human);
            bool hideMoz = false; try { hideMoz = human.HideMoz; } catch { }
            var sb = new System.Text.StringBuilder();
            sb.Append($"hideMoz={hideMoz} kokanCovered={covered}");
            foreach (var r in entry.Targets)
            {
                if (r == null) continue;
                try
                {
                    var go = r.gameObject;
                    string nm = r.name;
                    bool isMnp = nm == "mnpa" || nm == "mnpb";
                    bool isDan = nm == "o_dankon" || nm == "o_dan_f";
                    if (ALUncensorPlugin.ForceShow.Value && !covered && (isMnp || (isDan && human.Sex == 0)))
                    {
                        if (!go.activeSelf) go.SetActive(true);
                        if (!r.enabled) r.enabled = true;
                        // group nodes the game toggles: n_mnpb / n_dankon (and their n_body parents)
                        var t = go.transform.parent; int hops = 0;
                        while (t != null && hops++ < 4)
                        {
                            var pn = t.name;
                            if (pn == "cf_o_root" || pn == "BodyTop" || t.parent == null) break;
                            if (!t.gameObject.activeSelf && (pn == "n_mnpb" || pn == "n_dankon" || pn == "n_body" || pn == "n_body_al_parts"))
                                t.gameObject.SetActive(true);
                            t = t.parent;
                        }
                    }
                    var smr = r.TryCast<SkinnedMeshRenderer>();
                    string mesh = "?";
                    try { var m = smr != null ? smr.sharedMesh : null; mesh = m != null ? $"{m.name}/{m.vertexCount}v" : "null"; } catch { }
                    string chain = "";
                    try { var t = go.transform.parent; int hops = 0; while (t != null && hops++ < 3) { chain += $"{t.name}={(t.gameObject.activeSelf ? 1 : 0)}>"; t = t.parent; } } catch { }
                    sb.Append($" | {nm}: active={go.activeSelf}/{go.activeInHierarchy} enabled={r.enabled} mesh={mesh} parents[{chain}]");
                }
                catch (Exception e) { sb.Append($" | ?: {e.Message}"); }
            }
            string state = sb.ToString();
            int key = human.GameObject != null ? human.GameObject.GetInstanceID() : 0;
            if (ALUncensorPlugin.VerboseLog.Value && (!_lastState.TryGetValue(key, out var prev) || prev != state))
            {
                _lastState[key] = state;
                ALUncensorPlugin.Logger.LogInfo($"    [{reason}] {human.Name} state: {state}");
            }
        }

        private static int Swap(Entry entry, Human human, string reason)
        {
            var skinMat = entry.Skin.sharedMaterial;
            if (skinMat == null) return 0;
            ForceShowAndDiagnose(entry, human, reason);
            ApplyHairToSkin(entry, human);
            int n = 0;
            foreach (var r in entry.Targets)
            {
                if (r == null) continue;
                try
                {
                    var cur = r.sharedMaterial;
                    string curName = "null";
                    var kind = KindFor(r, human);
                    Material want = kind != CloneKind.None ? CloneFor(entry, r, skinMat, kind) : skinMat;
                    if (cur != null)
                    {
                        if (cur.GetInstanceID() == want.GetInstanceID()) continue; // already ours
                        bool alive = true;
                        try { curName = cur.name; } catch { alive = false; }   // destroyed material
                        if (alive && !IsMosaicMaterial(cur))
                        {
                            // Something non-mosaic is here. If it's a stale skin instance (old
                            // material from before a reload) refresh it, otherwise leave it alone.
                            if (cur.shader == null || cur.shader.name != ALUncensorPlugin.SkinShaderName) continue;
                        }
                    }
                    r.sharedMaterial = want;
                    n++;
                    if (ALUncensorPlugin.VerboseLog.Value)
                        ALUncensorPlugin.Logger.LogInfo($"    [{reason}] {human.Name}: {r.name} '{curName}' -> '{want.name}'");
                }
                catch (Exception e)
                {
                    ALUncensorPlugin.Logger.LogWarning($"    [{reason}] swap failed on a renderer: {e.Message}");
                }
            }
            return n;
        }
    }
}
