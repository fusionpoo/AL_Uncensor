#!/usr/bin/env python3
"""inject_dankon2.py — port DilleDing's Aicomi o_dankon into Amanatsu's two o_dankon meshes.
v2: keeps DilleDing's own penis UV layout (so a glans detail mask can be used) and carries vertex
colours / UV1-3 interpolated from Amanatsu's male body so the AL/skin_body shader gets every input."""
import struct, argparse, numpy as np, UnityPy, UnityPy.config, trimesh
from UnityPy.helpers import MeshHelper
from scipy.spatial import cKDTree
UnityPy.config.FALLBACK_UNITY_VERSION = "2022.3.34f1"
ap = argparse.ArgumentParser()
ap.add_argument("--al", required=True); ap.add_argument("--ac", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--scale", type=float, default=10.0); ap.add_argument("--packer", default="lz4")
ap.add_argument("--girth", type=float, default=1.0, help="radial scale of the shaft/glans about the penis axis (1 = DilleDing's, 0.85 = 15%% thinner)")
ap.add_argument("--girth-blend", type=float, default=0.0, help="fraction of the length over which the scale eases in from the base (base ring keeps its size)")
ap.add_argument("--flat-uv", action="store_true", help="old behaviour: squash UVs into a flat skin patch")
ap.add_argument("--uv-center", default="0.650,0.195"); ap.add_argument("--uv-size", default="0.018,0.018")
args = ap.parse_args()

def align16(n): return (n + 15) & ~15
def bp_mats(tt): return [np.array([bp[f"e{i}{j}"] for i in range(4) for j in range(4)]).reshape(4, 4) for bp in tt["m_BindPose"]]
def read_mesh(m):
    mh = MeshHelper.MeshHandler(m); mh.process()
    pos = np.array(mh.m_Vertices, np.float32).reshape(-1, 3); n = len(pos)
    g = lambda a, d: np.array(a, np.float32).reshape(n, d) if a is not None else None
    return dict(pos=pos, nrm=g(mh.m_Normals, 3), tan=g(mh.m_Tangents, 4), uv=g(mh.m_UV0, 2), uv1=g(mh.m_UV1, 2), uv2=g(mh.m_UV2, 2), uv3=g(mh.m_UV3, 2),
                col=g(mh.m_Colors, 4), bw=np.array(mh.m_BoneWeights, np.float32).reshape(n, -1), bi=np.array(mh.m_BoneIndices, np.int64).reshape(n, -1),
                idx=np.array(mh.m_IndexBuffer, np.int64).reshape(-1, 3))
def smrs(env, name):
    objs = {o.path_id: o for o in env.objects}; out = []
    for o in env.objects:
        if o.type.name == "SkinnedMeshRenderer":
            s = o.read()
            if s.m_GameObject.read().m_Name == name: out.append((o, s, objs))
    return out
def bone_names(s, objs): return [objs[b.path_id].read().m_GameObject.read().m_Name for b in s.m_Bones]
def aabb(p):
    mn, mx = p.min(0), p.max(0); c, e = (mn + mx) / 2, (mx - mn) / 2
    return dict(m_Center=dict(x=float(c[0]), y=float(c[1]), z=float(c[2])), m_Extent=dict(x=float(e[0]), y=float(e[1]), z=float(e[2])))

ac = UnityPy.load(args.ac); so, ss, sobjs = smrs(ac, "o_dankon")[0]
src = read_mesh(sobjs[ss.m_Mesh.path_id].read()); src_bones = bone_names(ss, sobjs)
src_bp = dict(zip(src_bones, bp_mats(sobjs[ss.m_Mesh.path_id].read_typetree())))
src_pos = {b: -src_bp[b][:3, 3] for b in src_bones}
print(f"[src] o_dankon {len(src['pos'])} verts, uv0 range {src['uv'].min(0)}..{src['uv'].max(0)}")

al = UnityPy.load(args.al); targets = smrs(al, "o_dankon"); assert len(targets) == 2
lo = targets[0][2]
# male body donor for colours / uv1-3: the o_body whose bone list has cf_s_kokanskin (the full male body)
donor = None
for o, s, objs in smrs(al, "o_body"):
    names = bone_names(s, objs)
    if "cf_s_kokanskin" in names and len(names) > 90: donor = read_mesh(objs[s.m_Mesh.path_id].read()); break
assert donor is not None, "male o_body donor not found"
print(f"[dst] donor o_body {len(donor['pos'])} verts, colours={donor['col'] is not None}")
DM = trimesh.Trimesh(vertices=donor["pos"], faces=donor["idx"], process=False)

A = "cf_j_dan101_00"
to0, ts0, _ = targets[0]; tt0 = lo[ts0.m_Mesh.path_id].read_typetree(); dst_bones0 = bone_names(ts0, lo)
dst_pos = {b: -M[:3, 3] for b, M in zip(dst_bones0, bp_mats(tt0))}
pos = ((src["pos"] - src_pos[A]) * args.scale + dst_pos[A]).astype(np.float32)
nrm, tan = src["nrm"].copy(), src["tan"]
if tan is None: tan = np.tile(np.array([1, 0, 0, 1], np.float32), (len(pos), 1))
if abs(args.girth - 1.0) > 1e-6:
    # radial scale about the axis dan101 -> dan109, eased in from the base so the join with the body is untouched
    B = "cf_j_dan109_00"; base = dst_pos[A]; axis = dst_pos[B] - base; length = np.linalg.norm(axis); axis /= length
    t = (pos - base) @ axis; span = float(t.max())                                   # 0 at the base ring, span at the tip
    ease = np.clip(t / max(span * args.girth_blend, 1e-6), 0, 1); ease = ease * ease * (3 - 2 * ease)
    sc = 1 + (args.girth - 1) * ease
    radial = pos - base - np.outer(t, axis)
    pos = (base + np.outer(t, axis) + radial * sc[:, None]).astype(np.float32)
    n_ax = nrm @ axis; n_rad = nrm - np.outer(n_ax, axis)
    nrm = n_rad / sc[:, None] + np.outer(n_ax, axis); nrm = (nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-8)).astype(np.float32)
    print(f"[dst] girth x{args.girth} (eased over the first {args.girth_blend:.0%} of the length; tip at {span:.2f} along the axis)")
uv = np.clip(src["uv"], 0, 1).astype(np.float32)
if args.flat_uv:
    uvc = np.array([float(x) for x in args.uv_center.split(",")]); uvs = np.array([float(x) for x in args.uv_size.split(",")])
    uv = (uvc + (uv - 0.5) * uvs).astype(np.float32)
# colours / uv1-3 from the nearest point on the male body
closest, dist, fid = DM.nearest.on_surface(pos)
bary = np.clip(trimesh.triangles.points_to_barycentric(donor["pos"][donor["idx"][fid]], closest), 0, 1); bary /= np.maximum(bary.sum(1, keepdims=True), 1e-8)
interp = lambda a: (a[donor["idx"][fid]] * bary[:, :, None]).sum(1).astype(np.float32)
# AL vertex colour = object-space smoothed normal (n*0.5+0.5)*255, alpha 255 (verified on the vanilla body)
_w = cKDTree(pos).query_ball_point(pos, 1e-4); sm = np.array([nrm[g].mean(0) for g in _w]); sm /= np.maximum(np.linalg.norm(sm, axis=1, keepdims=True), 1e-8)
col = np.concatenate([(sm * 0.5 + 0.5) * 255.0, np.full((len(pos), 1), 255.0)], 1).astype(np.float32)
uv1, uv2, uv3 = [interp(donor[k]) if donor[k] is not None else np.zeros((len(pos), 2), np.float32) for k in ("uv1", "uv2", "uv3")]
print(f"[dst] body attrs interpolated (nearest-surface dist mean {dist.mean():.3f}, max {dist.max():.3f}); colour mean {col.mean(0).round(1)}")

bw = src["bw"].astype(np.float32)
if bw.shape[1] < 4: bw = np.pad(bw, ((0, 0), (0, 4 - bw.shape[1])))
bw /= np.maximum(bw.sum(1, keepdims=True), 1e-8)
idx = src["idx"].reshape(-1).astype(np.uint16); n = len(pos)

for to, ts, objs in targets:
    mobj = objs[ts.m_Mesh.path_id]; tt = mobj.read_typetree(); dst_bones = bone_names(ts, objs)
    m = {i: dst_bones.index(nm) for i, nm in enumerate(src_bones)}
    bi = np.vectorize(lambda i: m[int(i)])(src["bi"]).astype(np.uint32)
    if bi.shape[1] < 4: bi = np.pad(bi, ((0, 0), (0, 4 - bi.shape[1])))
    s0 = np.concatenate([pos, nrm, tan], 1).astype("<f4").tobytes()
    colb = np.clip(np.rint(col), 0, 255).astype(np.uint8)
    s1 = b"".join(colb[i].tobytes() + np.concatenate([uv[i], uv1[i], uv2[i], uv3[i]]).astype("<f4").tobytes() for i in range(n))
    s2 = b"".join(struct.pack("<4f4I", *bw[i], *bi[i]) for i in range(n))
    data = b"".join(st + b"\0" * (align16(len(st)) - len(st)) for st in (s0, s1, s2))
    ch = [dict(stream=0, offset=0, format=0, dimension=0) for _ in range(14)]
    ch[0] = dict(stream=0, offset=0, format=0, dimension=3); ch[1] = dict(stream=0, offset=12, format=0, dimension=3); ch[2] = dict(stream=0, offset=24, format=0, dimension=4)
    ch[3] = dict(stream=1, offset=0, format=2, dimension=4); ch[4] = dict(stream=1, offset=4, format=0, dimension=2); ch[5] = dict(stream=1, offset=12, format=0, dimension=2)
    ch[6] = dict(stream=1, offset=20, format=0, dimension=2); ch[7] = dict(stream=1, offset=28, format=0, dimension=2)
    ch[12] = dict(stream=2, offset=0, format=0, dimension=4); ch[13] = dict(stream=2, offset=16, format=10, dimension=4)
    tt["m_VertexData"] = dict(m_CurrentChannels=0, m_VertexCount=n, m_Channels=ch, m_DataSize=data)
    tt["m_IndexFormat"] = 0; tt["m_IndexBuffer"] = idx.astype("<u2").tobytes()
    box = aabb(pos)
    tt["m_SubMeshes"] = [dict(firstByte=0, indexCount=int(len(idx)), topology=0, baseVertex=0, firstVertex=0, vertexCount=n, localAABB=box)]
    tt["m_LocalAABB"] = box
    bps = bp_mats(tt); baabb = []
    for b in range(len(dst_bones)):
        sel = ((bi == b) & (bw > 0)).any(1); vs = pos[sel] if sel.any() else pos
        local = (bps[b] @ np.concatenate([vs, np.ones((len(vs), 1), np.float32)], 1).T).T[:, :3]; mn, mx = local.min(0), local.max(0)
        baabb.append(dict(m_Min=dict(x=float(mn[0]), y=float(mn[1]), z=float(mn[2])), m_Max=dict(x=float(mx[0]), y=float(mx[1]), z=float(mx[2]))))
    tt["m_BonesAABB"] = baabb; tt["m_VariableBoneCountWeights"] = {"m_Data": []}
    tt["m_CompressedMesh"]["m_Vertices"] = dict(m_NumItems=0, m_Range=0.0, m_Start=0.0, m_Data=b"", m_BitSize=0)
    tt["m_MeshMetrics[0]"] = float(tt["m_MeshMetrics[0]"]); tt["m_RootBoneNameHash"] = int(tt["m_RootBoneNameHash"])
    mobj.save_typetree(tt); print(f"[dst] rewrote o_dankon mesh pid={mobj.path_id}: {n} verts, {len(idx)//3} tris")
data = al.file.save(packer=args.packer); open(args.out, "wb").write(data); print(f"[out] {args.out} ({len(data)} bytes)")
