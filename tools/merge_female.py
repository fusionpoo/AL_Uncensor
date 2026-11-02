#!/usr/bin/env python3
"""
merge_female.py — v3 (single-mesh merge)

Cuts the vulva (+ anus) region out of DilleDing's Aicomi female body and injects it into Amanatsu
Location's body_00.unity3d as the female `mnpb` / `mnpa` renderer meshes.

Differences from v1 (which showed vanilla skin poking through in H):
  * skin weights are TRANSFERRED from Amanatsu's own lower body (nearest vertex), so the patch and
    the body deform identically in any pose instead of drifting apart;
  * Amanatsu's crotch surface is CONFORMED onto DilleDing's surface (sunk to `--margin` under it)
    with a smooth blend-out to the untouched body, on all 5 lower-body and 4 one-piece meshes, so
    nothing is left covering the patch rim;
  * the whole inner canal is included (selected by "deep inside the body" rather than radius only)
    so there is no hole to see the body through.
"""
import argparse, struct, collections, numpy as np
import UnityPy, UnityPy.config
from UnityPy.helpers import MeshHelper
from scipy.spatial import cKDTree

UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.34f1"
ap = argparse.ArgumentParser()
ap.add_argument("--al", required=True); ap.add_argument("--ac", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--vulva-radius", type=float, default=0.5, help="front/back half-extent of the vulva cut (AL units)")
ap.add_argument("--vulva-width", type=float, default=0.34, help="left/right half-extent of the vulva cut")
ap.add_argument("--anus-radius", type=float, default=0.28, help="0 = skip anus")
ap.add_argument("--offset", type=float, default=0.005, help="patch pushed outward along normals (AL units, 0.1 = 1 cm)")
ap.add_argument("--margin", type=float, default=0.02, help="body sunk this far under DilleDing's surface")
ap.add_argument("--blend-in", type=float, default=0.75, help="full conform inside this radius of the patch centre")
ap.add_argument("--blend-out", type=float, default=1.15, help="no change beyond this radius")
ap.add_argument("--uv-center", default="0.650,0.195"); ap.add_argument("--uv-size", default="0.018,0.018")
ap.add_argument("--keep-uv", action="store_true", help="keep DilleDing's UVs (same layout as Amanatsu, but the game paints pubic hair over the labia there)")
ap.add_argument("--skirt", type=float, default=0.08, help="depth of the sealing skirt hung from the patch rim into the body (0 = none)")
ap.add_argument("--rim-taper", type=float, default=0.08, help="patch offset fades to 0 within this distance of the rim")
ap.add_argument("--rim", type=float, default=0.10, help="width of body kept under the patch rim (hole is cut inside this)")
ap.add_argument("--conform-in", type=float, default=0.06, help="body fully conformed to DilleDing's surface within this distance of the patch rim")
ap.add_argument("--conform-out", type=float, default=0.40, help="no conforming beyond this distance from the rim")
ap.add_argument("--max-shift", type=float, default=0.12, help="clamp for any single vertex move")
ap.add_argument("--touch", type=float, default=0.03, help="body verts closer than this to the patch surface are treated as covered")
ap.add_argument("--labia-mask", default=None, help="also write the plugin's labia_mask.r (pink tint weight map in body UV space) here")
ap.add_argument("--perineum", type=float, default=0.22, help="radius of the capsule joining vulva and anus cuts into one patch")
ap.add_argument("--no-hole", action="store_true", help="keep the body under the patch (only sink it) instead of cutting a hole")
ap.add_argument("--packer", default="lzma", choices=["lzma", "lz4", "original"])
args = ap.parse_args()
uvc = np.array([float(x) for x in args.uv_center.split(",")]); uvs = np.array([float(x) for x in args.uv_size.split(",")])
SCALE = 10.0
FMT_SIZE = {0: 4, 1: 2, 2: 1, 3: 1, 4: 2, 5: 2, 6: 1, 7: 1, 8: 2, 9: 2, 10: 4, 11: 4}

def bp_mats(tt): return [np.array([bp[f"e{i}{j}"] for i in range(4) for j in range(4)]).reshape(4, 4) for bp in tt["m_BindPose"]]
def mat_to_tt(M): return {f"e{i}{j}": float(M[i, j]) for i in range(4) for j in range(4)}
def align16(n): return (n + 15) & ~15
def aabb(p):
    mn, mx = p.min(0), p.max(0); c, e = (mn + mx) / 2, (mx - mn) / 2
    return dict(m_Center=dict(x=float(c[0]), y=float(c[1]), z=float(c[2])), m_Extent=dict(x=float(e[0]), y=float(e[1]), z=float(e[2])))
def smoothstep(x): x = np.clip(x, 0, 1); return x * x * (3 - 2 * x)
def read_mesh(m):
    mh = MeshHelper.MeshHandler(m); mh.process(); n = len(mh.m_Vertices)
    return dict(pos=np.array(mh.m_Vertices, np.float32).reshape(n, 3), nrm=np.array(mh.m_Normals, np.float32).reshape(n, 3),
                tan=np.array(mh.m_Tangents, np.float32).reshape(n, 4) if mh.m_Tangents is not None else None,
                uv=np.array(mh.m_UV0, np.float32).reshape(n, 2), idx=np.array(mh.m_IndexBuffer, np.int64).reshape(-1, 3),
                col=np.array(mh.m_Colors, np.float32).reshape(n, 4) if mh.m_Colors is not None else None,
                uv1=np.array(mh.m_UV1, np.float32).reshape(n, 2) if mh.m_UV1 is not None else None,
                uv2=np.array(mh.m_UV2, np.float32).reshape(n, 2) if mh.m_UV2 is not None else None,
                uv3=np.array(mh.m_UV3, np.float32).reshape(n, 2) if mh.m_UV3 is not None else None,
                bw=np.array(mh.m_BoneWeights, np.float32).reshape(n, -1), bi=np.array(mh.m_BoneIndices, np.int64).reshape(n, -1))

# ------------------------------------------------------------ Aicomi (DilleDing) female body
ac = UnityPy.load(args.ac); ao = {o.path_id: o for o in ac.objects}
for o in ac.objects:
    if o.type.name == "SkinnedMeshRenderer":
        s = o.read()
        if s.m_GameObject.read().m_Name == "o_body" and ao[s.m_Mesh.path_id].read().m_Name == "o_body":
            ss = s; break
S = read_mesh(ao[ss.m_Mesh.path_id].read()); S["pos"] *= SCALE
src_bones = [ao[b.path_id].read().m_GameObject.read().m_Name for b in ss.m_Bones]
src_bp = bp_mats(ao[ss.m_Mesh.path_id].read_typetree())
src_pos = {b: np.linalg.inv(src_bp[i])[:3, 3] * SCALE for i, b in enumerate(src_bones)}
KOK, ANA = src_pos["cf_j_kokan"], src_pos["cf_s_ana"]
print(f"[src] DilleDing female body: {len(S['pos'])} verts")
# weld coincident vertices (UV / normal seam splits) to get the real topology
_wt = cKDTree(S["pos"]); WELD = np.array([min(g) for g in _wt.query_ball_point(S["pos"], 1e-4)])
_we = {}
for t in S["idx"]:
    w = WELD[t]
    for a, b in ((w[0], w[1]), (w[1], w[2]), (w[2], w[0])):
        if a != b: _we[(min(a, b), max(a, b))] = _we.get((min(a, b), max(a, b)), 0) + 1
SRC_BOUNDARY = {e for e, c in _we.items() if c == 1}
print(f"[src] welded: {len(set(WELD))} unique verts, {len(SRC_BOUNDARY)} real boundary edges")

# ------------------------------------------------------------ Amanatsu
al = UnityPy.load(args.al); lo = {o.path_id: o for o in al.objects}
al_bp, al_hash, smrs, lower01 = {}, {}, {}, None
for o in al.objects:
    if o.type.name != "SkinnedMeshRenderer": continue
    s = o.read(); go = s.m_GameObject.read().m_Name
    names = [lo[b.path_id].read().m_GameObject.read().m_Name for b in s.m_Bones]
    tt = lo[s.m_Mesh.path_id].read_typetree()
    for n, M, b, h in zip(names, bp_mats(tt), s.m_Bones, tt["m_BoneNameHashes"]):
        al_bp.setdefault(n, (M, b.path_id)); al_hash.setdefault(n, h)
    if go in ("mnpb", "mnpa"):
        smrs.setdefault(go, []).append((o, s, len(s.m_Bones), lo[s.m_RootBone.path_id].read().m_GameObject.read().m_Name))
    if go == "o_lower_type01":
        lower01 = (read_mesh(lo[s.m_Mesh.path_id].read()), names)
female_mnpb = max(smrs["mnpb"], key=lambda x: x[2])
female_mnpa = [x for x in smrs["mnpa"] if x[3] == "cf_j_hips"][0]
L, L_bones = lower01
Ltree = cKDTree(L["pos"])
import trimesh
LMESH = trimesh.Trimesh(vertices=L["pos"], faces=L["idx"], process=False)
print(f"[dst] donor has colors={L['col'] is not None} uv1={L['uv1'] is not None} uv2={L['uv2'] is not None} uv3={L['uv3'] is not None}")

def surface_interp(points):
    """closest point on the donor body -> (face ids, barycentric weights)"""
    closest, dist, fid = LMESH.nearest.on_surface(points)
    tri = L["pos"][L["idx"][fid]]
    bary = trimesh.triangles.points_to_barycentric(tri, closest)
    bary = np.clip(bary, 0, 1); bary /= np.maximum(bary.sum(1, keepdims=True), 1e-8)
    return fid, bary

def interp_attr(attr, fid, bary):
    return (attr[L["idx"][fid]] * bary[:, :, None]).sum(1)

DROPPED = []
def interp_weights(fid, bary):
    n = len(fid); out_w = np.zeros((n, 4), np.float32); out_i = np.zeros((n, 4), np.int64)
    for k in range(n):
        acc = {}
        for c in range(3):
            v = L["idx"][fid[k], c]
            for w, b in zip(L["bw"][v], L["bi"][v]):
                if w > 0: acc[int(b)] = acc.get(int(b), 0.0) + float(w) * float(bary[k, c])
        top = sorted(acc.items(), key=lambda x: -x[1])[:4]
        tot = sum(w for _, w in top) or 1.0
        DROPPED.append(1.0 - tot)
        for j, (b, w) in enumerate(top): out_i[k, j] = b; out_w[k, j] = w / tot
    return out_w, out_i
print(f"[dst] mnpb smr={female_mnpb[0].path_id}, mnpa smr={female_mnpa[0].path_id}; weight donor o_lower_type01 ({len(L['pos'])} verts, {len(L_bones)} bones)")

# signed distance of DilleDing verts to Amanatsu's surface (>0 outside)
dS, jS = Ltree.query(S["pos"])
signedS = np.einsum("ij,ij->i", S["pos"] - L["pos"][jS], L["nrm"][jS])

def region_mask(center, radius, deep_radius, deep, width=None):
    d = S["pos"] - center
    if width is None: dist = np.linalg.norm(d, axis=1)
    else: dist = np.sqrt((d[:, 0] / width) ** 2 + (d[:, 1] / radius) ** 2 + (d[:, 2] / radius) ** 2) * radius
    return (dist < radius) | ((dist < deep_radius) & (signedS < -deep)), dist

def capsule_mask(a, b, r):
    ab = b - a; t = np.clip(((S["pos"] - a) @ ab) / (ab @ ab), 0, 1)
    return np.linalg.norm(S["pos"] - (a + t[:, None] * ab), axis=1) < r

def select(sel, core_dist, core_radius):
    tris = S["idx"][sel[S["idx"]].all(1)]
    parent = {}
    def find(a):
        parent.setdefault(a, a)
        while parent[a] != a: parent[a] = parent[parent[a]]; a = parent[a]
        return a
    for t in tris:                                        # connectivity on WELDED ids (seam splits must not cut the region)
        w = WELD[t]
        for a, b in ((w[0], w[1]), (w[1], w[2])):
            ra, rb = find(a), find(b)
            if ra != rb: parent[ra] = rb
    core = {find(WELD[v]) for v in np.unique(tris) if core_dist[v] < core_radius * 0.5}
    tris = np.array([t for t in tris if find(WELD[t[0]]) in core])
    used = np.unique(tris); remap = np.full(len(S["pos"]), -1); remap[used] = np.arange(len(used))
    return used, remap[tris]

def cap_and_rim(tris, used, pos, nrm, tan, uv, bw, bi_src, extra, max_len=16):
    """Welded-topology analysis of a cut patch: returns (tris, arrays..., rim_local_ids, n_capped).
    rim  = boundary edges created by the cut (not boundary in the source mesh)
    caps = real source openings (canal ends) inside the patch, closed with a fan"""
    wid = WELD[used]                                    # welded id per local vertex
    rep_local = {}
    for i, w in enumerate(wid): rep_local.setdefault(int(w), i)
    edges = {}
    for t in tris:
        w = wid[t]
        for a, b in ((w[0], w[1]), (w[1], w[2]), (w[2], w[0])):
            if a != b: edges[(min(a, b), max(a, b))] = edges.get((min(a, b), max(a, b)), 0) + 1
    bnd = [e for e, c in edges.items() if c == 1]
    # loops of boundary edges (welded ids)
    adj = {}
    for a, b in bnd: adj.setdefault(a, []).append(b); adj.setdefault(b, []).append(a)
    seen, loops = set(), []
    for v0 in adj:
        if v0 in seen: continue
        loop, prev, cur = [v0], None, v0
        while True:
            seen.add(cur); nxt = [x for x in adj[cur] if x != prev and x not in seen]
            if not nxt:
                break
            nxt = nxt[0]; loop.append(nxt); prev, cur = cur, nxt
            if len(loop) > 10000: break
        loops.append(loop)
    # classify: a loop is part of the outer rim if its vertices sit on the outer skin; a loop that lies
    # inside the body (sliced canal end) or is a real opening of the source mesh gets capped
    rim_w = set(); cap_loops = []
    for loop in loops:
        L = [rep_local[int(w)] for w in loop]
        depth = float(np.mean(signedS[used[L]]))          # signed dist to Amanatsu skin, <0 = inside
        src_open = all(((min(loop[i], loop[(i + 1) % len(loop)]), max(loop[i], loop[(i + 1) % len(loop)])) in SRC_BOUNDARY) for i in range(len(loop)))
        if src_open or depth < -0.06: cap_loops.append((loop, depth, src_open))
        else: rim_w.update(int(w) for w in loop)
    rim_local = [i for i, w in enumerate(wid) if int(w) in rim_w]
    print(f"    loops: {[(len(l), round(float(np.mean(signedS[used[[rep_local[int(w)] for w in l]]])),3)) for l in loops]} -> rim verts {len(rim_local)}, capping {[(len(l), round(d,3), o) for l,d,o in cap_loops]}")
    loops = [l for l, _, _ in cap_loops]
    tri_dirs = {(int(wid[t[i]]), int(wid[t[(i + 1) % 3]])) for t in tris for i in range(3)}
    new_tris = []; added = 0
    for loop in loops:
        if len(loop) < 3: continue
        L = [rep_local[int(w)] for w in loop]
        c = len(pos)
        pos = np.vstack([pos, pos[L].mean(0)[None]]); n_ = nrm[L].mean(0); nrm = np.vstack([nrm, (n_ / (np.linalg.norm(n_) + 1e-9))[None]])
        tan = np.vstack([tan, tan[L][:1]]); uv = np.vstack([uv, uv[L].mean(0)[None]])
        bw = np.vstack([bw, bw[L][:1]]); bi_src = np.vstack([bi_src, bi_src[L][:1]]); extra = np.vstack([extra, extra[L].mean(0)[None]])
        for i in range(len(loop)):
            a, b = loop[i], loop[(i + 1) % len(loop)]
            la, lb = rep_local[int(a)], rep_local[int(b)]
            new_tris.append([lb, la, c] if (int(a), int(b)) in tri_dirs else [la, lb, c])
        added += 1
    if new_tris: tris = np.vstack([tris, np.array(new_tris)])
    print(f"    welded: {len(bnd)} boundary edges, rim verts {len(rim_local)}, capped {added} loop(s)")
    rim_edges = [(a, b) for a, b in bnd if a in rim_w and b in rim_w]
    return tris, pos, nrm, tan, uv, bw, bi_src, rim_local, added, extra, (rim_edges, tri_dirs, rep_local)

# =====================================================================================================
# v3: instead of overlaying a separate patch on a hole, the patch is STITCHED INTO every crotch body
# mesh (o_lower_type*/o_onepi_type*) so the result is one closed skin mesh: no open edges for the
# outline pre-pass to draw, no second mesh that can drift in a pose, nothing to see under.
# =====================================================================================================
def build_patch(label, used, tris):
    pos = S["pos"][used].copy(); nrm, tan = S["nrm"][used].copy(), S["tan"][used].copy(); uv = S["uv"][used].copy()
    fid, bary = surface_interp(S["pos"][used])
    bw, bi_src = interp_weights(fid, bary)
    # AL vertex colour = object-space smoothed normal encoded (n*0.5+0.5)*255, alpha 255 (verified on the vanilla body)
    sm = np.zeros_like(nrm); wid_ = WELD[used]
    for w_ in np.unique(wid_):
        g = wid_ == w_; sm[g] = nrm[g].mean(0)
    sm /= np.maximum(np.linalg.norm(sm, axis=1, keepdims=True), 1e-8)
    col = np.concatenate([(sm * 0.5 + 0.5) * 255.0, np.full((len(used), 1), 255.0)], 1).astype(np.float32)
    uvx = [interp_attr(L[k], fid, bary) if L[k] is not None else np.zeros((len(used), 2), np.float32) for k in ("uv1", "uv2", "uv3")]
    extra = np.concatenate([col] + uvx, 1)
    tris, pos, nrm, tan, uv, bw, bi_src, rim_local, capped, extra, (rim_edges, tri_dirs, rep_local) = cap_and_rim(tris, used, pos, nrm, tan, uv, bw, bi_src, extra)
    if not args.keep_uv:
        lo_, hi_ = uv.min(0), uv.max(0); uv = uvc + ((uv - lo_) / np.maximum(hi_ - lo_, 1e-6) - 0.5) * uvs
    # ordered, directed rim loop (welded ids), walking the way the patch triangles walk it
    nxt = {}
    for a, b in rim_edges:
        if (a, b) not in tri_dirs: a, b = b, a
        nxt[a] = b
    start = next(iter(nxt)); loop = [start]; cur = nxt[start]
    while cur != start and len(loop) < 10000: loop.append(cur); cur = nxt.get(cur, start)
    if len(loop) != len(nxt): print(f"    WARNING: rim of {label} is not a single loop ({len(loop)} of {len(nxt)})")
    wid = WELD[used]; splits = {}
    for i, w in enumerate(wid): splits.setdefault(int(w), []).append(i)
    print(f"[{label}] {len(pos)} verts, {len(tris)} tris, rim loop {len(loop)}, {capped} capped; weight mass dropped by top-4: max {max(DROPPED):.4f}"); DROPPED.clear()
    bone_names = np.array(L_bones, dtype=object)[bi_src]                    # names per weight slot
    return dict(label=label, pos=pos, nrm=nrm, tan=tan, uv=uv, col=extra[:, :4], uv1=extra[:, 4:6], uv2=extra[:, 6:8], uv3=extra[:, 8:10],
                bw=bw, bnames=bone_names, tris=tris, rim_loop=loop, splits=splits, rim_local=rim_local)

vu_sel, vu_dist = region_mask(KOK, args.vulva_radius, args.vulva_radius * 2.2, 0.08, width=args.vulva_width)
regions = [(KOK, args.vulva_radius)]; sel = vu_sel
if args.anus_radius > 0:
    an_sel, _ = region_mask(ANA, args.anus_radius, args.anus_radius * 2.0, 0.08)
    sel = sel | an_sel | capsule_mask(KOK, ANA, args.perineum); regions.append((ANA, args.anus_radius))
    print(f"[src] kokan-anus distance {np.linalg.norm(KOK - ANA):.3f}, perineum capsule r={args.perineum}")
used_, tris_ = select(sel, vu_dist, args.vulva_radius)
patches = [build_patch("vulva+anus" if args.anus_radius > 0 else "vulva", used_, tris_)]

if args.labia_mask:
    # depth-weighted map of the inside of the slit, rasterised in body-UV space for the plugin's pink tint
    P_, UV_, sg_ = S["pos"][used_], S["uv"][used_], signedS[used_]
    inner = (sg_ < -0.02) & (np.abs(P_[:, 0]) < 0.16) & (P_[:, 2] > -0.32) & (P_[:, 2] < 0.36)
    wgt = np.clip((-sg_ - 0.02) / 0.06, 0, 1) * inner
    u0, u1, v0, v1, res = 0.470, 0.530, 0.500, 0.570, 4096
    Wm, Hm = int((u1 - u0) * res), int((v1 - v0) * res); img = np.zeros((Hm, Wm), np.float32)
    for t in tris_:
        if wgt[t].max() <= 0: continue
        xs = (UV_[t, 0] - u0) / (u1 - u0) * Wm; ys = (UV_[t, 1] - v0) / (v1 - v0) * Hm
        xmin, xmax = int(max(0, np.floor(xs.min()))), int(min(Wm - 1, np.ceil(xs.max()))); ymin, ymax = int(max(0, np.floor(ys.min()))), int(min(Hm - 1, np.ceil(ys.max())))
        if xmin > xmax or ymin > ymax: continue
        gx, gy = np.meshgrid(np.arange(xmin, xmax + 1) + 0.5, np.arange(ymin, ymax + 1) + 0.5)
        (x0, y0), (x1, y1), (x2, y2) = zip(xs, ys); det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(det) < 1e-9: continue
        l0 = ((y1 - y2) * (gx - x2) + (x2 - x1) * (gy - y2)) / det; l1 = ((y2 - y0) * (gx - x2) + (x0 - x2) * (gy - y2)) / det; l2 = 1 - l0 - l1
        m = (l0 >= -1e-3) & (l1 >= -1e-3) & (l2 >= -1e-3); val = l0 * wgt[t][0] + l1 * wgt[t][1] + l2 * wgt[t][2]
        sub = img[ymin:ymax + 1, xmin:xmax + 1]; sub[m] = np.maximum(sub[m], val[m])
    from PIL import Image, ImageFilter
    a_ = np.array(Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)))
    open(args.labia_mask, "wb").write(struct.pack("<4s4fII", b"ALLM", u0, v0, u1, v1, Wm, Hm) + a_.tobytes())
    print(f"[mask] labia mask {Wm}x{Hm} -> {args.labia_mask}")

PM = trimesh.util.concatenate([trimesh.Trimesh(vertices=p["pos"], faces=p["tris"], process=False) for p in patches])
RIMTREE = cKDTree(np.concatenate([p["pos"][p["rim_local"]] for p in patches]))
near = np.zeros(len(S["pos"]), bool)
for c, r in regions: near |= np.linalg.norm(S["pos"] - c, axis=1) < args.blend_out * 1.5
Stree = cKDTree(S["pos"][near]); SN = S["nrm"][near]; SP = S["pos"][near]
def first_hit(origins, dirs):
    t = np.full(len(origins), np.inf)
    for a in range(0, len(origins), 400):
        locs, idx_ray, _ = PM.ray.intersects_location(origins[a:a + 400], dirs[a:a + 400], multiple_hits=True)
        if len(idx_ray):
            dist = np.linalg.norm(locs - origins[a + idx_ray], axis=1)
            for r_, d_ in zip(idx_ray, dist):
                if d_ < t[a + r_]: t[a + r_] = d_
    return t

def parse_body(tt):
    vd = tt["m_VertexData"]; n = vd["m_VertexCount"]; ch = vd["m_Channels"]
    want = {0: (0, 0, 0, 3), 1: (0, 12, 0, 3), 2: (0, 24, 0, 4), 3: (1, 0, 2, 4), 4: (1, 4, 0, 2), 5: (1, 12, 0, 2), 6: (1, 20, 0, 2), 7: (1, 28, 0, 2), 12: (2, 0, 0, 4), 13: (2, 16, 10, 4)}
    for k, (st, of, fm, dm) in want.items():
        c = ch[k]; assert (c["stream"], c["offset"], c["format"], c["dimension"]) == (st, of, fm, dm), f"unexpected layout on channel {k}: {c}"
    buf = bytes(vd["m_DataSize"]); o0, o1, o2 = 0, align16(40 * n), align16(40 * n) + align16(36 * n)
    s0 = np.frombuffer(buf[o0:o0 + 40 * n], "<f4").reshape(n, 10)
    s1 = np.frombuffer(buf[o1:o1 + 36 * n], np.uint8).reshape(n, 36)
    s2 = np.frombuffer(buf[o2:o2 + 32 * n], np.uint8).reshape(n, 32)
    uvs4 = s1[:, 4:].copy().view("<f4").reshape(n, 8)
    return dict(pos=s0[:, :3].copy(), nrm=s0[:, 3:6].copy(), tan=s0[:, 6:10].copy(), col=s1[:, :4].astype(np.float32),
                uv=uvs4[:, 0:2].copy(), uv1=uvs4[:, 2:4].copy(), uv2=uvs4[:, 4:6].copy(), uv3=uvs4[:, 6:8].copy(),
                bw=s2[:, :16].copy().view("<f4").reshape(n, 4), bi=s2[:, 16:].copy().view("<u4").reshape(n, 4))

def pack_body(B):
    n = len(B["pos"])
    s0 = np.concatenate([B["pos"], B["nrm"], B["tan"]], 1).astype("<f4").tobytes()
    colb = np.clip(np.rint(B["col"]), 0, 255).astype(np.uint8)
    uvs4 = np.concatenate([B["uv"], B["uv1"], B["uv2"], B["uv3"]], 1).astype("<f4")
    s1 = np.concatenate([colb, uvs4.view(np.uint8).reshape(n, 32)], 1).tobytes()
    s2 = np.concatenate([B["bw"].astype("<f4").view(np.uint8).reshape(n, 16), B["bi"].astype("<u4").view(np.uint8).reshape(n, 16)], 1).tobytes()
    return b"".join(st + b"\0" * (align16(len(st)) - len(st)) for st in (s0, s1, s2))

def zip_loops(A, R, PA, PR):
    """bridge two closed loops (index lists) walked in the same sense: returns triangles (a_{i+1}, a_i, r_j) / (a_i, r_j, r_{j+1})"""
    n, m = len(A), len(R)
    # align starts at the closest pair
    d = np.linalg.norm(PA[:, None] - PR[None], axis=2); i0, j0 = np.unravel_index(np.argmin(d), d.shape)
    A = A[i0:] + A[:i0]; PA = np.roll(PA, -i0, 0); R = R[j0:] + R[:j0]; PR = np.roll(PR, -j0, 0)
    i = j = 0; out = []
    while i < n or j < m:
        ai, aj = A[i % n], R[j % m]
        da = np.linalg.norm(PA[(i + 1) % n] - PR[j % m]) if i < n else np.inf
        dr = np.linalg.norm(PA[i % n] - PR[(j + 1) % m]) if j < m else np.inf
        if da <= dr: out.append((A[(i + 1) % n], ai, aj)); i += 1
        else: out.append((ai, aj, R[(j + 1) % m])); j += 1
    return out

FEMALE_GO = ("o_lower_type", "o_onepi_type")
for o in al.objects:
    if o.type.name != "SkinnedMeshRenderer": continue
    s = o.read(); go = s.m_GameObject.read().m_Name
    if not go.startswith(FEMALE_GO): continue
    mobj = lo[s.m_Mesh.path_id]; tt = mobj.read_typetree(); B = parse_body(tt); n0 = len(B["pos"])
    bnames = [lo[b.path_id].read().m_GameObject.read().m_Name for b in s.m_Bones]
    bindposes = bp_mats(tt); hashes = list(tt["m_BoneNameHashes"]); bone_pids = [b.path_id for b in s.m_Bones]
    pos, nrm = B["pos"], B["nrm"]
    raw = tt["m_IndexBuffer"]; raw = bytes(raw) if not isinstance(raw, (bytes, bytearray)) else raw
    ib = np.frombuffer(raw, dtype="<u2" if tt["m_IndexFormat"] == 0 else "<u4").reshape(-1, 3).astype(np.int64)
    # --- conform the crotch onto DilleDing's surface (blend) and find the footprint under the patches
    # candidates: anything within reach of a patch; conform weight falls off with distance from the patch RIM
    # (not the centre), so only the ring that gets bridged is pulled onto DilleDing's surface
    drim = RIMTREE.query(pos)[0]
    cand = np.where(drim < args.blend_out)[0]
    w = 1 - smoothstep((drim - args.conform_in) / max(args.conform_out - args.conform_in, 1e-6))
    t_out = first_hit(pos[cand], nrm[cand]); t_in = first_hit(pos[cand], -nrm[cand])
    in_fp = np.zeros(n0, bool); in_fp[cand] = (np.isfinite(t_in) & (t_in < 0.6)) | (np.isfinite(t_out) & (t_out < 0.6))
    _, dpatch, _ = PM.nearest.on_surface(pos[cand]); in_fp[cand] |= dpatch < args.touch      # sitting on/inside the patch counts too
    dd, jj = Stree.query(pos[cand]); signed = np.einsum("ij,ij->i", pos[cand] - SP[jj], SN[jj])
    shift = np.clip(signed * w[cand], -args.max_shift, args.max_shift)
    shift[dd > 0.35] = 0                                                       # no nearby DilleDing surface -> leave alone
    pos[cand] -= nrm[cand] * shift[:, None]                                    # onto DilleDing's outer surface
    print(f"    conform: {np.count_nonzero(shift)} verts moved, max |shift| {np.abs(shift).max():.3f}, clipped {(np.abs(signed * w[cand]) > args.max_shift).sum()}")
    # --- weld body verts by position for topology
    bt = cKDTree(pos); wb = np.array([min(g) for g in bt.query_ball_point(pos, 1e-4)])
    keep = ~in_fp[ib].any(1); kept = ib[keep]; removed = ib[~keep]
    orig_dir = {(int(wb[t[i]]), int(wb[t[(i + 1) % 3]])) for t in ib for i in range(3)}
    kept_dir = {(int(wb[t[i]]), int(wb[t[(i + 1) % 3]])) for t in kept for i in range(3)}
    hole_edges = [(a, b) for (a, b) in kept_dir if (b, a) not in kept_dir and (b, a) in orig_dir]   # newly exposed edges only
    nxt = {}
    for a, b in hole_edges: nxt.setdefault(a, []).append(b)
    loops, used_e = [], set()
    for a0 in list(nxt):
        for b0 in nxt[a0]:
            if (a0, b0) in used_e: continue
            loop, cur, prev = [a0], b0, a0; used_e.add((a0, b0))
            while cur != a0 and len(loop) < 5000:
                loop.append(cur); outs = [x for x in nxt.get(cur, []) if (cur, x) not in used_e]
                if not outs: break
                # at a pinch vertex prefer the edge that turns back toward the loop start's neighbourhood: take the closest continuation
                x = min(outs, key=lambda x: np.linalg.norm(pos[x] - pos[loop[0]])) if len(outs) > 1 else outs[0]
                used_e.add((cur, x)); prev, cur = cur, x
            loops.append(loop)
    # --- assign loops to patches, zip the biggest, cap the rest
    rep_body = {}
    for i, wv in enumerate(wb): rep_body.setdefault(int(wv), []).append(i)
    new_tris = []; V = {k: [B[k]] for k in ("pos", "nrm", "tan", "col", "uv", "uv1", "uv2", "uv3", "bw")}; BI = [B["bi"]]; nv = n0
    def add_bone(name):
        if name not in bnames:
            bnames.append(name); bindposes.append(al_bp[name][0]); hashes.append(int(al_hash[name])); bone_pids.append(al_bp[name][1])
        return bnames.index(name)
    patch_base = []
    for p in patches:
        base = nv; patch_base.append(base); npv = len(p["pos"])
        for k in V: V[k].append(p[k])
        bi = np.zeros((npv, 4), np.uint32)
        for i in range(npv):
            for k in range(4):
                if p["bw"][i, k] > 0: bi[i, k] = add_bone(p["bnames"][i, k])
        BI.append(bi); nv += npv
        new_tris.append(p["tris"] + base)
    rim_pts = [p["pos"][[p["splits"][wid][0] for wid in p["rim_loop"]]] for p in patches]
    info = []
    by_patch = {k: [] for k in range(len(patches))}
    for loop in loops:
        if len(loop) < 3: continue
        P = pos[loop]; dists = [cKDTree(rp).query(P)[0].mean() for rp in rim_pts]
        k = int(np.argmin(dists)); by_patch[k].append(loop)
    for k, p in enumerate(patches):
        ls = sorted(by_patch[k], key=len, reverse=True)
        if not ls: print(f"    WARNING {go}: no hole loop found for {p['label']}"); continue
        main = ls[0]
        R = list(reversed(p["rim_loop"]))                                     # same sense as the body loop
        PR = np.array([p["pos"][p["splits"][wid][0]] for wid in R])
        A = main; PA = pos[A]
        # resolve welded ids -> real vertex ids, choosing the UV-nearest split at seams
        def body_v(wid, uvref):
            c = rep_body[wid]; return c[0] if len(c) == 1 else min(c, key=lambda i: np.linalg.norm(B["uv"][i] - uvref))
        def patch_v(wid, uvref):
            c = p["splits"][wid]; return patch_base[k] + (c[0] if len(c) == 1 else min(c, key=lambda i: np.linalg.norm(p["uv"][i] - uvref)))
        tri_out = []
        n_, m_ = len(A), len(R)
        d = np.linalg.norm(PA[:, None] - PR[None], axis=2); i0, j0 = np.unravel_index(np.argmin(d), d.shape)
        A2 = A[i0:] + A[:i0]; PA2 = np.roll(PA, -i0, 0); R2 = R[j0:] + R[:j0]; PR2 = np.roll(PR, -j0, 0)
        i = j = 0
        while i < n_ or j < m_:
            da = np.linalg.norm(PA2[(i + 1) % n_] - PR2[j % m_]) if i < n_ else np.inf
            dr = np.linalg.norm(PA2[i % n_] - PR2[(j + 1) % m_]) if j < m_ else np.inf
            rw = R2[j % m_]; ruv = p["uv"][p["splits"][rw][0]]
            if da <= dr:
                a1, a0 = body_v(A2[(i + 1) % n_], ruv), body_v(A2[i % n_], ruv); tri_out.append([a1, a0, patch_v(rw, B["uv"][a0])]); i += 1
            else:
                a0 = body_v(A2[i % n_], ruv); r1 = R2[(j + 1) % m_]
                tri_out.append([a0, patch_v(rw, B["uv"][a0]), patch_v(r1, B["uv"][a0])]); j += 1
        # the greedy zip can fold where the two loops cross in projection: flip any bridge triangle whose face
        # normal points against its vertex normals (otherwise it is back-face culled and its outline hull pokes out)
        tri_out = np.array(tri_out); allpos = np.concatenate(V["pos"], 0); allnrm = np.concatenate(V["nrm"], 0)
        fn_ = np.cross(allpos[tri_out[:, 1]] - allpos[tri_out[:, 0]], allpos[tri_out[:, 2]] - allpos[tri_out[:, 0]])
        flip = np.einsum("ij,ij->i", fn_, allnrm[tri_out].mean(1)) < 0
        tri_out[flip] = tri_out[flip][:, ::-1]
        new_tris.append(tri_out); info.append(f"{p['label']}: loop {len(main)} <-> rim {len(R)} -> {len(tri_out)} bridge tris ({flip.sum()} flipped)")
        for extra_loop in ls[1:]:                                            # small leftover holes: fan cap
            L_ = [rep_body[wv][0] for wv in extra_loop]
            c = nv; nv += 1
            for kk in V: V[kk].append(np.mean(V[kk][0][L_], 0, keepdims=True).astype(V[kk][0].dtype))
            BI.append(B["bi"][L_[:1]])
            new_tris.append(np.array([[rep_body[extra_loop[(q + 1) % len(extra_loop)]][0], rep_body[extra_loop[q]][0], c] for q in range(len(extra_loop))]))
            info.append(f"{p['label']}: capped stray loop of {len(extra_loop)}")
    # --- assemble
    for kk in V: V[kk] = np.concatenate(V[kk], 0)
    bi_all = np.concatenate(BI, 0).astype(np.uint32); V["bi"] = bi_all
    tris_all = np.concatenate([kept] + new_tris, 0).astype(np.int64)
    assert tris_all.max() < nv and nv < 65536
    tt["m_VertexData"]["m_VertexCount"] = int(nv); tt["m_VertexData"]["m_DataSize"] = pack_body(V)
    tt["m_IndexFormat"] = 0; tt["m_IndexBuffer"] = tris_all.reshape(-1).astype("<u2").tobytes()
    box = aabb(V["pos"])
    tt["m_SubMeshes"] = [dict(firstByte=0, indexCount=int(tris_all.size), topology=0, baseVertex=0, firstVertex=0, vertexCount=int(nv), localAABB=box)]
    tt["m_LocalAABB"] = box; tt["m_BindPose"] = [mat_to_tt(M) for M in bindposes]; tt["m_BoneNameHashes"] = hashes
    tt["m_RootBoneNameHash"] = int(tt["m_RootBoneNameHash"]); tt["m_MeshMetrics[0]"] = float(tt["m_MeshMetrics[0]"])
    baabb = []
    for b in range(len(bnames)):
        selb = ((bi_all == b) & (V["bw"] > 0)).any(1); vs = V["pos"][selb] if selb.any() else V["pos"]
        local = (bindposes[b] @ np.concatenate([vs, np.ones((len(vs), 1), np.float32)], 1).T).T[:, :3]
        mn, mx = local.min(0), local.max(0)
        baabb.append(dict(m_Min=dict(x=float(mn[0]), y=float(mn[1]), z=float(mn[2])), m_Max=dict(x=float(mx[0]), y=float(mx[1]), z=float(mx[2]))))
    tt["m_BonesAABB"] = baabb; tt["m_VariableBoneCountWeights"] = {"m_Data": []}
    tt["m_CompressedMesh"]["m_Vertices"] = dict(m_NumItems=0, m_Range=0.0, m_Start=0.0, m_Data=b"", m_BitSize=0)
    mobj.save_typetree(tt)
    stt = o.read_typetree(); stt["m_Bones"] = [dict(m_FileID=0, m_PathID=int(pid)) for pid in bone_pids]; o.save_typetree(stt)
    print(f"[merge] {go}: {len(removed)} tris removed, loops {[len(l) for l in loops]}, verts {n0}->{nv}, tris {len(ib)}->{len(tris_all)}, bones {len(s.m_Bones)}->{len(bnames)}; " + "; ".join(info))

# the old genital renderers now draw nothing (the geometry lives in the body meshes)
for go_, entry in (("mnpb", female_mnpb), (("mnpa"), female_mnpa)):
    o_, s_, _, _ = entry; mobj = lo[s_.m_Mesh.path_id]; tt = mobj.read_typetree()
    tt["m_IndexBuffer"] = b""
    for sm in tt["m_SubMeshes"]: sm["indexCount"] = 0
    tt["m_MeshMetrics[0]"] = float(tt["m_MeshMetrics[0]"]); tt["m_RootBoneNameHash"] = int(tt["m_RootBoneNameHash"])
    mobj.save_typetree(tt); print(f"[blank] {go_} mesh emptied")

data = al.file.save(packer=args.packer); open(args.out, "wb").write(data)
print(f"[out] {args.out} ({len(data)} bytes, {args.packer})")
