"""Pre-rendered squad-member sprites (single figures, a field tent, the Colossus).

Run (from the repo root):
    /tmp/claude-0/blendenv/bin/python tools/blender/render_units.py [name ...] [--sheet=PATH]

Reuses the toon pipeline of render_sprites.py (emission-only banded shading
with a fixed upper-left key, inverted-hull outline in #1b1a14, orthographic
camera looking along +Y tilted 7 degrees down, Cycles CPU, Pillow post).

Figures are rendered with ONE fixed orthographic scale (100 px per world
unit) onto a fixed 256x256 canvas: the figure's ground point (world origin)
is at x=128 and the lowest opaque row is snapped so the soles sit exactly
on y=250 (rows 0..249 hold the figure).  The tent uses the same scale on a
512x256 canvas.  The Colossus follows the vehicle convention (tight crop,
4 px padding top/left/right, none at the bottom, long side 640 px).

Writes assets/units/<name>_idle.png, <name>_attack.png and units.json.
All insignia are fictional (white cross on olive for the medic, original
glyphs for the Lantern Bureau).
"""
import json
import math
import os
import random
import shutil
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Euler, Matrix, Vector  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import render_sprites as rs  # noqa: E402
from render_sprites import box, cyl, prism, sphere, toon  # noqa: E402

ROOT = rs.ROOT
OUT_DIR = os.path.join(ROOT, "assets", "units")

PPU = 100            # final pixels per world unit (fixed for every figure)
SS = 4               # supersampling factor of the raw render
BASE = 250           # baseline row (soles sit on this line)
FIG_YAW = -25.0      # figures turn a little toward the camera, still facing +X
SAMPLES = 6
FIG_OUTLINE = 0.04   # hull thickness in world units (~4 px on the canvas)
TILT = rs.TILT


def rad(a):
    return math.radians(a)


def M(loc=(0, 0, 0), rot=(0, 0, 0), s=1.0):
    sc = Vector((s, s, s)) if isinstance(s, (int, float)) else Vector(s)
    return Matrix.LocRotScale(Vector(loc), Euler([rad(a) for a in rot], "XYZ"), sc)


_COL = {}


def C(h, emissive=False):
    """Toon material for a hex colour (cached per render)."""
    return toon(("E" if emissive else "C") + h, h, emissive=emissive)


# --------------------------------------------------------------------------
# grouping: objects built inside `with Group(...)` are parented to an empty
# so parts can be modelled in local coordinates.
# --------------------------------------------------------------------------
class Group:
    stack = []

    def __init__(self, mat=None, name="grp", **kw):
        self.mat = mat if mat is not None else M(**kw)
        self.name = name

    def __enter__(self):
        e = bpy.data.objects.new(self.name, None)
        bpy.context.scene.collection.objects.link(e)
        if Group.stack:
            e.parent = Group.stack[-1].empty
        e.matrix_basis = self.mat
        self.empty = e
        self.mark = len(rs.Ctx.objects)
        Group.stack.append(self)
        return self

    def __exit__(self, *a):
        for ob in rs.Ctx.objects[self.mark:]:
            if ob.parent is None:
                ob.parent = self.empty
        Group.stack.pop()


# --------------------------------------------------------------------------
# extra primitives
# --------------------------------------------------------------------------
def rod(name, p0, p1, r, mat, r2=None, verts=16, caps=True, outline=1.0, smooth=True):
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    L = max(d.length, 1e-4)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=caps, cap_tris=False, segments=verts,
                          radius1=r, radius2=r if r2 is None else r2, depth=L)
    q = Vector((0, 0, 1)).rotation_difference(d.normalized() if d.length > 1e-6
                                              else Vector((0, 0, 1)))
    bmesh.ops.transform(bm, matrix=Matrix.Translation((p0 + p1) / 2) @ q.to_matrix().to_4x4(),
                        verts=bm.verts)
    return rs._finish(bm, name, mat, smooth=smooth, outline=outline)


def capsule(name, p0, p1, r0, r1, mat, segs=16, outline=1.0):
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    L = d.length
    bm = bmesh.new()
    if L > 1e-4:
        bmesh.ops.create_cone(bm, cap_ends=False, cap_tris=False, segments=segs,
                              radius1=r0, radius2=r1, depth=L)
        bmesh.ops.translate(bm, vec=(0, 0, L / 2), verts=bm.verts)
    for r, z in ((r0, 0.0), (r1, L)):
        ret = bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=segs // 2, radius=r)
        bmesh.ops.translate(bm, vec=(0, 0, z), verts=ret["verts"])
    q = Vector((0, 0, 1)).rotation_difference(d.normalized() if L > 1e-4 else Vector((0, 0, 1)))
    bmesh.ops.transform(bm, matrix=Matrix.Translation(p0) @ q.to_matrix().to_4x4(),
                        verts=bm.verts)
    return rs._finish(bm, name, mat, smooth=True, sharp_angle=80, outline=outline)


def lathe(name, prof, mat, a0=0.0, a1=360.0, segs=32, loc=(0, 0, 0), rot=(0, 0, 0),
          scale=(1, 1, 1), outline=1.0, sharp=40):
    """Revolve a closed (r, z) profile around Z (optionally a partial sweep)."""
    full = abs(a1 - a0) >= 359.99
    n = segs if full else max(2, int(round(segs * abs(a1 - a0) / 360)))
    cnt = n if full else n + 1
    bm = bmesh.new()
    rings = []
    for i in range(cnt):
        a = rad(a0 + (a1 - a0) * i / n)
        rings.append([bm.verts.new((r * math.cos(a) * scale[0], r * math.sin(a) * scale[1],
                                    z * scale[2])) for r, z in prof])
    m = len(prof)
    for i in range(n):
        A, B = rings[i], rings[(i + 1) % cnt]
        for j in range(m):
            k = (j + 1) % m
            bm.faces.new((A[j], B[j], B[k], A[k]))
    if not full:
        bm.faces.new(rings[0])
        bm.faces.new(list(reversed(rings[-1])))
    return rs._finish(bm, name, mat, loc, rot, smooth=True, sharp_angle=sharp, outline=outline)


def dome(name, r, loc, mat, scale=(1, 1, 1), rot=(0, 0, 0), segs=24, rings=12, outline=1.0):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=r)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -1e-4], context="VERTS")
    bmesh.ops.scale(bm, vec=Vector(scale), verts=bm.verts)
    return rs._finish(bm, name, mat, loc, rot, smooth=True, sharp_angle=80, outline=outline)


def tube(name, pts, r, mat, radii=None, res=8, outline=1.0):
    cu = bpy.data.curves.new(name + "_cu", "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = r
    cu.bevel_resolution = 3
    cu.resolution_u = res
    cu.use_fill_caps = True
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(pts) - 1)
    for k, p in enumerate(pts):
        bp = sp.bezier_points[k]
        bp.co = Vector(p)
        bp.handle_left_type = bp.handle_right_type = "AUTO"
        if radii:
            bp.radius = radii[k]
    cob = bpy.data.objects.new(name + "_tmp", cu)
    bpy.context.scene.collection.objects.link(cob)
    dg = bpy.context.evaluated_depsgraph_get()
    me = bpy.data.meshes.new_from_object(cob.evaluated_get(dg))
    bpy.data.objects.remove(cob)
    bm = bmesh.new()
    bm.from_mesh(me)
    bpy.data.meshes.remove(me)
    return rs._finish(bm, name, mat, smooth=True, sharp_angle=80, outline=outline)


def sph(r, az, el):
    """Point on a sphere: az from +X toward +Y, el up from the XY plane (degrees)."""
    a, e = rad(az), rad(el)
    return Vector((r * math.cos(e) * math.cos(a), r * math.cos(e) * math.sin(a), r * math.sin(e)))


def ik(S, T, a, b, pole):
    """Two-bone IK; stretches the limb straight if the target is out of reach."""
    S, T = Vector(S), Vector(T)
    d = T - S
    L = max(d.length, 1e-4)
    if L >= (a + b) * 0.995:
        k = L / ((a + b) * 0.995)
        a, b = a * k, b * k
    cosA = max(-1.0, min(1.0, (a * a + L * L - b * b) / (2 * a * L)))
    A = math.acos(cosA)
    u = d / L
    p = Vector(pole)
    p = p - u * p.dot(u)
    if p.length < 1e-5:
        p = Vector((0, 0, -1)) - u * u.z
    p.normalize()
    return S + u * (a * math.cos(A)) + p * (a * math.sin(A))


def cross_patch(name, loc, rot, size, olive, white, rim=None):
    """Fictional medic mark: white cross on an olive patch (optional light rim)."""
    with Group(M(loc, rot), name=name):
        if rim is not None:
            box(name + "_rim", (0.01, size * 1.25, size * 1.25), (-0.004, 0, 0), rim,
                bevel=0.0, outline=0.0)
        box(name + "_bg", (0.012, size, size), (0, 0, 0), olive, bevel=0.0, outline=0.0)
        a = size * 0.72
        w = size * 0.24
        box(name + "_v", (0.014, w, a), (0.003, 0, 0), white, bevel=0.0, outline=0.0)
        box(name + "_h", (0.014, a, w), (0.003, 0, 0), white, bevel=0.0, outline=0.0)


# --------------------------------------------------------------------------
# palettes
# --------------------------------------------------------------------------
ALLY = dict(uniform="#5f6c35", trousers="#56612f", webbing="#b3a26f", helmet="#55602f",
            skin="#e2b48a", boot="#3e2f22", shin="#7d7a4e", wood="#7a4a28",
            metal="#3b3d38", eye="#1b1a14", pack="#8f8657", hand="#e2b48a")
ENEMY = dict(coat="#6e736a", coat_dark="#5c6158", trousers="#565a52", helmet="#5d625a",
             crest="#3d413a", rubber="#45483f", lens="#b7c9ad", rim="#2b2c27",
             can="#8c8a72", boot="#2a2925", belt="#34352f", hand="#3a3933",
             buckle="#8a7a4a", metal="#3b3d38", wood="#6b4a2c", shin="#2a2925")
OLIVE_PATCH = "#6a7838"
WHITE = "#f2f0e6"
BRASS = "#c4993e"
MINT = rs.MINT


class Kit:
    def __init__(self, pal, **over):
        p = dict(pal)
        p.update(over)
        self.hex = p
        for k, v in p.items():
            setattr(self, k, C(v))


# --------------------------------------------------------------------------
# the figure rig
# --------------------------------------------------------------------------
HIP_Z = 0.56
THIGH, SHIN = 0.205, 0.205
UPPER, FORE = 0.27, 0.25
BOOT = (0.28, 0.17, 0.14)


class Rig:
    """A chunky toy soldier. Body frame: +X forward, +Z up, -Y toward camera.

    side = -1 is the near (right) side, +1 the far (left) side.
    """

    def __init__(self, kit, faction, hip=(0, 0, HIP_Z), lean=0.0, twist=0.0,
                 head_yaw=0.0, head_pitch=0.0, broad=1.0):
        self.k = kit
        self.faction = faction
        self.hip = Vector(hip)
        self.broad = broad
        self.T = M(hip, (0, lean, -twist))
        self.head_c = self.T @ Vector((0.04, 0, 0.95))
        self.H = M(self.head_c, (0, head_pitch, head_yaw))
        self.lean, self.twist = lean, twist
        self.arms = {}

    def tp(self, p):
        return self.T @ Vector(p)

    def shoulder(self, side):
        return self.tp((0.0, side * 0.27 * self.broad, 0.56))

    # ---- legs ----------------------------------------------------------
    def leg(self, side, fx, pitch=0.0, knee=None, pole=(1, 0, 0.15), lift=0.0, fy=None):
        k = self.k
        y = side * 0.12 * self.broad if fy is None else fy
        hip = self.hip + Vector((0, side * 0.11 * self.broad, -0.03))
        R = Euler((0, rad(pitch), 0)).to_matrix()
        corners = [R @ Vector((sx * BOOT[0] / 2, 0, sz * BOOT[2] / 2))
                   for sx in (-1, 1) for sz in (-1, 1)]
        cz = lift - min(c.z for c in corners)
        c = Vector((fx, y, cz))
        box("boot", BOOT, c, k.boot, rot=(0, pitch, 0), bevel=0.05, seg=2)
        ankle = c + R @ Vector((-0.045, 0, 0.085))
        if knee is None:
            knee = ik(hip, ankle, THIGH, SHIN, pole)
        capsule("thigh", hip, knee, 0.105, 0.092, k.trousers)
        capsule("shin", knee, ankle, 0.09, 0.082, k.shin)
        return knee

    def stance(self, back=-0.09, front=0.09, lift=0.0):
        self.leg(-1, back, lift=lift)
        self.leg(1, front, lift=lift)

    def kneel(self, front=0.22, back_knee_x=-0.02):
        """Near knee on the ground, far foot planted in front."""
        self.leg(1, front, pole=(1, 0, 0.6))
        knee = Vector((back_knee_x, -0.12, 0.09))
        self.leg(-1, back_knee_x - 0.26, pitch=58, knee=knee)

    # ---- arms ----------------------------------------------------------
    def arm(self, side, hand, pole=None, sleeve=None, glove=None, hand_r=0.08):
        k = self.k
        S = self.shoulder(side)
        if pole is None:
            pole = (-0.2, side * 0.6, -1)
        E = ik(S, hand, UPPER, FORE, pole)
        sl = sleeve or (k.uniform if self.faction == "ally" else k.coat)
        capsule("uarm", S, E, 0.09 * self.broad, 0.08, sl)
        capsule("farm", E, hand, 0.08, 0.07, sl)
        sphere("hand", hand_r, hand, glove or k.hand, scale=(1.1, 1, 1))
        self.arms[side] = (S, E)
        return S, E

    # ---- body ----------------------------------------------------------
    def body(self, pack=True, coat_len=0.22, coat_open=False):
        k = self.k
        b = self.broad
        if self.faction == "ally":
            box("pelvis", (0.30, 0.40 * b, 0.22), self.hip + Vector((0, 0, 0.0)), k.trousers,
                bevel=0.08)
            with Group(self.T, name="torso"):
                box("chest", (0.36, 0.48 * b, 0.64), (0, 0, 0.38), k.uniform, bevel=0.14, seg=3)
                box("belt", (0.39, 0.51 * b, 0.09), (0, 0, 0.12), k.webbing, bevel=0.03)
                box("buckle", (0.03, 0.08, 0.06), (0.2, 0, 0.12), k.metal, bevel=0.01,
                    outline=0.5)
                for s in (-1, 1):
                    box("pouch", (0.09, 0.11, 0.12), (0.19, s * 0.13 * b, 0.15), k.webbing,
                        bevel=0.03, outline=0.7)
                    box("strap", (0.025, 0.06, 0.5), (0.18, s * 0.12 * b, 0.43), k.webbing,
                        rot=(s * 6, 0, 0), bevel=0.01, outline=0.5)
                if pack:
                    box("pack", (0.17, 0.36 * b, 0.32), (-0.25, 0, 0.42), k.pack, bevel=0.06)
                    rod("roll", (-0.24, -0.19 * b, 0.63), (-0.24, 0.19 * b, 0.63), 0.07,
                        k.trousers)
        else:
            z_top = self.hip.z + 0.14
            bot = max(0.06, coat_len)
            prof = [(0.25, z_top), (0.35, bot), (0.30, bot), (0.19, z_top)]
            if coat_open:
                lathe("skirt", prof, k.coat, a0=40, a1=320, segs=28, scale=(0.82 * b, b, 1))
            else:
                lathe("skirt", prof, k.coat, segs=28, scale=(0.82 * b, b, 1))
            box("pelvis", (0.30, 0.40 * b, 0.22), self.hip, k.trousers, bevel=0.08)
            with Group(self.T, name="torso"):
                box("chest", (0.36, 0.48 * b, 0.64), (0, 0, 0.38), k.coat, bevel=0.14, seg=3)
                rod("collar", (0.0, 0, 0.63), (0.01, 0, 0.73), 0.16 * b, k.coat_dark)
                box("belt", (0.39, 0.51 * b, 0.08), (0, 0, 0.16), k.belt, bevel=0.03)
                box("buckle", (0.03, 0.09, 0.07), (0.2, 0, 0.16), k.buckle, bevel=0.01,
                    outline=0.5)
                for s in (-1, 1):
                    box("pouch", (0.08, 0.12, 0.11), (0.19, s * 0.14 * b, 0.2), k.belt,
                        bevel=0.03, outline=0.7)
                    box("board", (0.15, 0.09, 0.03), (0.0, s * 0.235 * b, 0.70), k.coat_dark,
                        bevel=0.01, outline=0.5)
                for z in (0.32, 0.45, 0.58):
                    sphere("button", 0.02, (0.185, -0.05, z), k.buckle, outline=0.0)
        # neck
        nk = k.skin if self.faction == "ally" else k.rubber
        capsule("neck", self.tp((0.02, 0, 0.62)), self.head_c + Vector((0, 0, -0.15)),
                0.1, 0.1, nk)

    # ---- heads -----------------------------------------------------------
    def face(self, eye_az=-32, moustache=False, brow=False):
        k = self.k
        sphere("head", 0.28, (0, 0, 0), k.skin, scale=(1.0, 0.95, 1.0), segs=28, rings=14)
        for az in (eye_az, -eye_az):
            sphere("eye", 0.036, sph(0.262, az, 2), C(ALLY["eye"]), scale=(0.7, 0.8, 1.3),
                   rot=(0, 0, az), outline=0.0)
        sphere("nose", 0.055, sph(0.27, -6, -12), k.skin, outline=0.6)
        sphere("ear", 0.065, sph(0.255, -92, -6), k.skin, scale=(0.6, 1, 1), outline=0.6)
        if moustache:
            box("tache", (0.05, 0.18, 0.05), sph(0.262, -10, -24), C("#4a3524"),
                rot=(0, 0, -10), bevel=0.02, outline=0.5)
        if brow:
            box("brow", (0.05, 0.13, 0.035), sph(0.27, eye_az, 14), C("#3a2c20"),
                rot=(0, -10, eye_az), bevel=0.01, outline=0.0)

    def ally_helmet(self, emblem=False, band=None):
        k = self.k
        prof = [(0.002, 0.255), (0.12, 0.245), (0.22, 0.20), (0.285, 0.12), (0.31, 0.035),
                (0.47, 0.0), (0.475, -0.03), (0.30, -0.02), (0.002, -0.02)]
        lathe("helmet", prof, k.helmet, loc=(0.0, 0, 0.07), rot=(0, -5, 0), segs=36)
        if band:
            lathe("hband", [(0.296, 0.10), (0.318, 0.10), (0.322, 0.04), (0.30, 0.04)],
                  C(band), loc=(0.0, 0, 0.07), rot=(0, -5, 0), segs=36, outline=0.0)
        rod("strap", sph(0.27, -70, 10), sph(0.27, -20, -55), 0.013, k.webbing, outline=0.4)
        if emblem:
            p = sph(0.29, -62, 28) + Vector((0, 0, 0.07))
            cross_patch("hpatch", p, (0, -28, -62), 0.13, C(OLIVE_PATCH), C(WHITE),
                        rim=C(WHITE))

    def mask(self, lens_hex=None, emissive=False):
        """Full gas mask with round lenses and a filter can."""
        k = self.k
        sphere("hood", 0.28, (0, 0, 0), k.rubber, scale=(1.0, 0.95, 1.0), segs=28, rings=14)
        sphere("muzzle", 1.0, (0.17, 0, -0.09), k.rubber, scale=(0.17, 0.2, 0.17), outline=0.8)
        lm = C(lens_hex or ENEMY["lens"], emissive=emissive)
        for az in (-30, 30):
            d = sph(1, az, 0)
            rod("lensrim", d * 0.24, d * 0.30, 0.1, k.rim, verts=20, outline=0.6)
            rod("lens", d * 0.25, d * 0.315, 0.082, lm, verts=20, outline=0.0)
        rod("snout", (0.27, 0, -0.13), (0.35, 0, -0.17), 0.07, k.rubber, outline=0.7)
        rod("can", (0.33, 0, -0.16), (0.43, 0, -0.33), 0.08, k.can, verts=18)
        rod("canrim", (0.42, 0, -0.31), (0.445, 0, -0.355), 0.088, k.rim, verts=18,
            outline=0.5)

    def enemy_helmet(self, crest_hex=None):
        k = self.k
        base = Vector((-0.01, 0, 0.11))
        dprof = [(0.002, 0.23), (0.14, 0.222), (0.24, 0.18), (0.30, 0.105), (0.322, 0.04),
                 (0.322, 0.0), (0.002, 0.0)]
        lathe("edome", dprof, k.helmet, loc=base, segs=36, scale=(1.05, 1, 1))
        sk = [(0.30, 0.04), (0.335, 0.045), (0.39, -0.10), (0.365, -0.11), (0.30, 0.0)]
        lathe("eskirt", sk, k.helmet, a0=55, a1=305, segs=36, loc=base, scale=(1.05, 1, 1))
        lip = [(0.30, 0.03), (0.335, 0.03), (0.37, -0.03), (0.34, -0.035), (0.30, 0.0)]
        lathe("elip", lip, k.helmet, a0=-56, a1=56, segs=36, loc=base, scale=(1.05, 1, 1))
        crest = C(crest_hex) if crest_hex else k.crest
        prism("crest", [(-0.3, 0.10), (-0.22, 0.30), (-0.06, 0.37), (0.08, 0.36),
                        (0.2, 0.29), (0.26, 0.17), (0.0, 0.2)], -0.05, 0.05, crest,
              bevel=0.015, loc=tuple(base))

    def ghillie(self, seed=3):
        rng = random.Random(seed)
        cols = [C("#4d5a2c"), C("#6b6a3a"), C("#3f4a24"), C("#7a6d45"), C("#5c6a32")]
        dome("ghood", 0.33, (-0.01, 0, 0.02), cols[0], scale=(1.0, 1.0, 0.95))
        lathe("gcape", [(0.30, 0.03), (0.34, 0.03), (0.40, -0.42), (0.36, -0.43),
                        (0.27, 0.0)], cols[2], a0=70, a1=290, segs=28, loc=(-0.01, 0, 0))
        for i in range(70):
            az = rng.uniform(-60, 300) if i < 55 else rng.uniform(70, 290)
            el = rng.uniform(5, 85) if i < 55 else rng.uniform(-50, 0)
            r0 = 0.32 if el > 0 else 0.36
            p0 = sph(r0, az, el)
            out = sph(1, az + rng.uniform(-20, 20), el * 0.3 - 30)
            ln = rng.uniform(0.12, 0.24)
            if -60 < az < 20 and el < 35:
                continue   # keep the face clear
            rod("strip", p0, p0 + out * ln, rng.uniform(0.025, 0.04), rng.choice(cols),
                r2=0.006, verts=6, outline=0.45, smooth=False)


# --------------------------------------------------------------------------
# weapons (local frame: +X along the barrel, origin at the rear grip)
# --------------------------------------------------------------------------
def w_rifle(k, L=0.78, sl=0.46, scope=False, wood=None):
    wood = wood or k.wood
    fe = 0.55 * L / 0.78
    pts = [(-sl, -0.13), (-sl, 0.035), (0.05, 0.03), (fe, 0.025), (fe + 0.03, -0.005),
           (fe, -0.035), (0.06, -0.04), (-0.03, -0.095), (-0.11, -0.075)]
    prism("stock", pts, -0.036, 0.036, wood, bevel=0.015)
    box("recv", (0.24, 0.06, 0.06), (0.06, 0, 0.055), k.metal, bevel=0.01, outline=0.8)
    rod("barrel", (0.15, 0, 0.05), (L, 0, 0.05), 0.024, k.metal, verts=12)
    rod("mring", (L - 0.05, 0, 0.05), (L, 0, 0.05), 0.032, k.metal, verts=12, outline=0.7)
    for x in (fe * 0.55, fe - 0.03):
        box("band", (0.03, 0.082, 0.078), (x, 0, -0.002), k.metal, bevel=0.005, outline=0.5)
    rod("bolt", (0.04, -0.03, 0.06), (0.05, -0.1, 0.02), 0.012, k.metal, outline=0.5)
    sphere("knob", 0.026, (0.05, -0.1, 0.02), k.metal, outline=0.5)
    box("fsight", (0.02, 0.016, 0.045), (L - 0.03, 0, 0.085), k.metal, bevel=0, outline=0.5)
    if scope:
        rod("scope", (-0.02, 0, 0.145), (0.3, 0, 0.145), 0.04, k.metal, verts=16)
        rod("bell1", (-0.08, 0, 0.145), (-0.01, 0, 0.145), 0.052, k.metal, verts=16)
        rod("bell2", (0.25, 0, 0.145), (0.35, 0, 0.145), 0.058, k.metal, verts=16)
        rod("glass", (0.348, 0, 0.145), (0.356, 0, 0.145), 0.045, C("#9fb9a8"), verts=16,
            outline=0.0)
        for x in (0.03, 0.22):
            box("mount", (0.03, 0.03, 0.07), (x, 0, 0.095), k.metal, bevel=0, outline=0.5)
    return dict(grip=Vector((-0.04, 0, -0.06)), fore=Vector((0.33 * L / 0.78, 0, -0.035)),
                muzzle=Vector((L + 0.01, 0, 0.05)))


def w_mg(k):
    dark = C("#2f302c")
    prism("mgstock", [(-0.5, -0.10), (-0.5, 0.06), (-0.38, 0.065), (-0.08, 0.05),
                      (-0.08, -0.03), (-0.38, -0.06)], -0.04, 0.04, k.wood, bevel=0.02)
    box("mgrecv", (0.46, 0.12, 0.16), (0.12, 0, 0.03), k.metal, bevel=0.025)
    box("mgcover", (0.26, 0.13, 0.04), (0.08, 0, 0.125), dark, bevel=0.01, outline=0.7)
    prism("mggrip", [(-0.06, -0.04), (0.03, -0.04), (0.0, -0.18), (-0.08, -0.17)],
          -0.03, 0.03, k.wood, bevel=0.012)
    rod("jacket", (0.34, 0, 0.04), (0.80, 0, 0.04), 0.062, k.metal, verts=18)
    for i in range(5):
        sphere("hole", 0.018, (0.42 + i * 0.08, -0.058, 0.04), C("#1b1a14"), outline=0.0)
    rod("mgbarrel", (0.8, 0, 0.04), (0.96, 0, 0.04), 0.027, k.metal, verts=12)
    rod("hider", (0.94, 0, 0.04), (1.03, 0, 0.04), 0.036, k.metal, r2=0.052, verts=14)
    box("mgsight", (0.025, 0.02, 0.06), (0.78, 0, 0.12), k.metal, bevel=0, outline=0.5)
    rod("handle", (0.28, 0, 0.17), (0.48, 0, 0.17), 0.016, k.metal, outline=0.5)
    for s in (-1, 1):
        rod("bipod", (0.74, s * 0.04, 0.0), (0.42, s * 0.055, -0.07), 0.018, k.metal,
            outline=0.6)
    # ammo belt hanging from the feed tray
    pts = rs.catenary((0.12, -0.04), (-0.16, -0.02), 0.34, n=13)
    for i, (x, z) in enumerate(pts):
        a, b2 = pts[max(0, i - 1)], pts[min(len(pts) - 1, i + 1)]
        ang = math.degrees(math.atan2(b2[1] - a[1], b2[0] - a[0]))
        box("round", (0.032, 0.03, 0.1), (x, -0.08, z), C(BRASS), rot=(0, -ang, 0),
            bevel=0.008, outline=0.55)
    return dict(grip=Vector((-0.03, 0, -0.08)), fore=Vector((0.46, 0, -0.03)),
                top=Vector((0.4, 0, 0.12)), muzzle=Vector((1.04, 0, 0.04)))


def w_shotgun(k, L=0.64):
    pts = [(-0.36, -0.12), (-0.36, 0.035), (0.0, 0.035), (0.0, -0.04), (-0.05, -0.09),
           (-0.11, -0.07)]
    prism("sgstock", pts, -0.036, 0.036, k.wood, bevel=0.015)
    box("sgrecv", (0.22, 0.065, 0.1), (0.08, 0, 0.02), k.metal, bevel=0.015)
    rod("sgbarrel", (0.15, 0, 0.05), (L, 0, 0.05), 0.03, k.metal, verts=12)
    rod("sgtube", (0.15, 0, 0.0), (L - 0.06, 0, 0.0), 0.025, k.metal, verts=12)
    rod("pump", (0.26, 0, 0.0), (0.44, 0, 0.0), 0.045, k.wood, verts=14)
    rod("shield", (0.2, 0, 0.06), (0.56, 0, 0.06), 0.042, C("#4a4c46"), verts=14, outline=0.7)
    for i in range(4):
        sphere("shole", 0.013, (0.25 + i * 0.09, -0.04, 0.065), C("#1b1a14"), outline=0.0)
    return dict(grip=Vector((-0.04, 0, -0.06)), fore=Vector((0.35, 0, -0.02)),
                muzzle=Vector((L + 0.01, 0, 0.05)))


def w_pistol(k):
    prism("pgrip", [(-0.03, 0.0), (0.04, 0.0), (0.015, -0.13), (-0.065, -0.12)],
          -0.025, 0.025, C("#3f3328"), bevel=0.01)
    box("slide", (0.22, 0.045, 0.06), (0.07, 0, 0.03), k.metal, bevel=0.01)
    rod("pbarrel", (0.17, 0, 0.035), (0.24, 0, 0.035), 0.016, k.metal, verts=10, outline=0.6)
    return dict(grip=Vector((-0.01, 0, -0.06)), muzzle=Vector((0.245, 0, 0.035)))


def w_stick(k, metal=None):
    rod("sthandle", (0, 0, 0), (0.27, 0, 0), 0.022, C("#8b6a3e"), verts=10)
    rod("sthead", (0.25, 0, 0), (0.36, 0, 0), 0.048, metal or C("#56604e"), verts=14)
    rod("stcap", (-0.015, 0, 0), (0.01, 0, 0), 0.026, k.metal, verts=10, outline=0.5)
    return dict(grip=Vector((0.07, 0, 0)), tip=Vector((0.36, 0, 0)))


def w_satchel(k, name="satchel"):
    box(name, (0.22, 0.11, 0.17), (0, 0, 0), C("#a79762"), bevel=0.03)
    box(name + "_band", (0.035, 0.12, 0.18), (0.04, 0, 0), C("#6b5d3a"), bevel=0.005,
        outline=0.5)
    rod(name + "_fuse", (-0.06, 0, 0.08), (-0.1, 0, 0.16), 0.012, C("#2f302c"), outline=0.5)
    return dict(grip=Vector((0.0, 0, 0.1)))


def w_club(k):
    wood = C("#5d4128")
    rod("chandle", (0, 0, 0), (0.36, 0, 0), 0.04, wood, verts=12)
    rod("chead", (0.34, 0, 0), (0.78, 0, 0), 0.07, wood, r2=0.11, verts=16)
    rod("cpommel", (-0.03, 0, 0), (0.02, 0, 0), 0.055, C("#3a3d37"), verts=12, outline=0.6)
    for x, r in ((0.42, 0.08), (0.7, 0.108)):
        rod("cband", (x - 0.025, 0, 0), (x + 0.025, 0, 0), r + 0.012, C("#3a3d37"),
            verts=16, outline=0.5)
    iron = C("#4c4f48")
    for i, (x, az) in enumerate([(0.5, -90), (0.6, -30), (0.62, 40), (0.52, 90), (0.74, -70),
                                 (0.76, 10), (0.66, -130), (0.48, 160)]):
        r = 0.07 + (x - 0.34) / 0.44 * 0.04
        d = Vector((0, -math.sin(rad(az + 90)), math.cos(rad(az + 90))))
        d = Vector((0, math.cos(rad(az)), math.sin(rad(az))))
        p = Vector((x, 0, 0)) + d * (r - 0.01)
        rod("spike", p, p + d * 0.1, 0.022, iron, r2=0.0, verts=8, outline=0.5, smooth=False)
    rod("ctip", (0.78, 0, 0), (0.9, 0, 0), 0.03, iron, r2=0.0, verts=8, outline=0.5,
        smooth=False)
    return dict(grip=Vector((0.06, 0, 0)), grip2=Vector((0.22, 0, 0)), tip=Vector((0.9, 0, 0)))


def w_nozzle(k):
    rod("wand", (-0.12, 0, 0), (0.62, 0, 0), 0.032, k.metal, verts=12)
    box("valve", (0.1, 0.07, 0.09), (0.02, 0, 0.0), C("#2f302c"), bevel=0.015)
    prism("fgrip", [(0.28, -0.01), (0.36, -0.01), (0.34, -0.14), (0.27, -0.13)],
          -0.028, 0.028, k.wood, bevel=0.01)
    prism("rgrip", [(-0.06, -0.01), (0.02, -0.01), (0.0, -0.13), (-0.07, -0.12)],
          -0.028, 0.028, k.wood, bevel=0.01)
    rod("ntip", (0.6, 0, 0), (0.7, 0, 0), 0.042, C("#2f302c"), r2=0.05, verts=14)
    rod("pilot", (0.55, 0, -0.05), (0.66, 0, -0.05), 0.016, C("#8a4b2a"), verts=8,
        outline=0.5)
    return dict(grip=Vector((-0.03, 0, -0.07)), fore=Vector((0.31, 0, -0.08)),
                muzzle=Vector((0.71, 0, 0)), rear=Vector((-0.12, 0, 0)))


def mortar_round(name, k):
    lathe(name, [(0.002, 0.16), (0.03, 0.15), (0.048, 0.10), (0.05, 0.04), (0.03, -0.02),
                 (0.018, -0.08), (0.002, -0.08)], C("#5d6355"), segs=16)
    for a in (0, 90):
        box(name + "_fin", (0.09, 0.01, 0.06), (0, 0, -0.07), k.metal, rot=(0, 0, a),
            bevel=0, outline=0.5)


# --------------------------------------------------------------------------
# figures.  Each builder takes the pose and returns the muzzle point in the
# body frame (before the root yaw).
# --------------------------------------------------------------------------
def ally_kit(**over):
    return Kit(ALLY, **over)


def enemy_kit(**over):
    return Kit(ENEMY, **over)


def place(W, p):
    return W @ Vector(p)


def aim_rig(kit, faction, **kw):
    a = dict(hip=(-0.02, 0, 0.55), lean=4, twist=45, head_yaw=10, head_pitch=6)
    a.update(kw)
    return Rig(kit, faction, **a)


def rifle_poses(R, pose, k, L=0.78, sl=0.46, scope=False, wood=None, low=False):
    """Shared rifle handling: port arms (idle) or shouldered aim (attack)."""
    if pose == "attack":
        Sn = R.shoulder(-1)
        W = M((Sn.x + 0.04 + sl, -0.24, Sn.z + 0.11), (0, 0, 0))
    elif low:
        W = M((0.2, -0.26, 0.78), (0, 20, 0))
    else:
        W = M((0.18, -0.25, 0.84), (0, -52, 0))
    with Group(W, name="rifle"):
        g = w_rifle(k, L=L, sl=sl, scope=scope, wood=wood)
    if pose == "attack":
        R.arm(-1, place(W, g["grip"]), pole=(-0.3, -1, -1.2))
        R.arm(1, place(W, g["fore"]), pole=(0.2, 0.3, -1))
    else:
        R.arm(-1, place(W, g["grip"]), pole=(-0.3, -0.6, -1))
        R.arm(1, place(W, g["fore"]), pole=(-0.2, 0.2, -1))
    return place(W, g["muzzle"])


def build_rifleman(pose):
    k = ally_kit()
    if pose == "attack":
        R = aim_rig(k, "ally")
        R.stance(-0.17, 0.17)
    else:
        R = Rig(k, "ally", head_yaw=0)
        R.stance()
    R.body()
    with Group(R.H, name="head"):
        R.face()
        R.ally_helmet()
    return rifle_poses(R, pose, k)


def build_veteran(pose):
    k = ally_kit()
    if pose == "attack":
        R = aim_rig(k, "ally")
        R.stance(-0.17, 0.17)
    else:
        R = Rig(k, "ally", twist=10)
        R.stance(-0.11, 0.11)
    R.body(pack=False)
    scarf = C("#9a4630")
    with Group(R.T, name="scarf"):
        lathe("scarf", [(0.10, 0.70), (0.2, 0.70), (0.21, 0.6), (0.1, 0.6)], scarf, segs=24,
              loc=(0.02, 0, 0))
        box("tail", (0.05, 0.1, 0.24), (0.15, -0.14, 0.52), scarf, rot=(0, -8, 12), bevel=0.02)
        box("tail2", (0.05, 0.09, 0.18), (0.15, -0.06, 0.52), scarf, rot=(0, -4, -6),
            bevel=0.02)
        # binocular case on the belt
        box("bcase", (0.1, 0.1, 0.14), (0.05, -0.27, 0.12), C("#6b5333"), bevel=0.03,
            outline=0.7)
    with Group(R.H, name="head"):
        R.face(moustache=True, brow=True)
        R.ally_helmet(band="#2f3418")
    if pose == "attack":
        mz = rifle_poses(R, pose, k, L=0.6, sl=0.42)
    else:
        W = M((0.14, -0.27, 0.86), (0, -70, 0))
        with Group(W, name="carbine"):
            g = w_rifle(k, L=0.6, sl=0.42)
        R.arm(-1, place(W, g["grip"]), pole=(-0.3, -0.6, -1))
        R.arm(1, (0.12, 0.2, 0.62), pole=(-0.5, 0.5, -1))
        mz = place(W, g["muzzle"])
    S, E = R.arms[-1]
    chevrons(R, -1, S, E, k.webbing)
    return mz


def chevrons(R, side, S, E, mat):
    u = (E - S).normalized()
    n = Vector((0, -1, 0))
    n = (n - u * n.dot(u)).normalized()
    w = u.cross(n).normalized()
    for i in range(3):
        c = S + u * (0.08 + i * 0.045) + n * 0.083
        apex = c + u * 0.03
        for sgn in (-1, 1):
            rod("chev", apex, c - u * 0.02 + w * sgn * 0.065, 0.013, mat, verts=8, outline=0.0)


def armband(R, S, E, k):
    u = (E - S).normalized()
    n = Vector((0, -1, 0))
    n = (n - u * n.dot(u)).normalized()
    c0, c1 = S + u * 0.1, S + u * 0.19
    rod("armband", c0, c1, 0.095, C(WHITE), verts=18, outline=0.6)
    mid = (c0 + c1) / 2 + n * 0.096
    # orient patch: x along n
    q = Vector((1, 0, 0)).rotation_difference(n)
    e = q.to_euler()
    cross_patch("apatch", mid, [math.degrees(a) for a in e], 0.075, C(OLIVE_PATCH), C(WHITE))


def build_medic(pose):
    k = ally_kit()
    if pose == "attack":
        R = Rig(k, "ally", hip=(0.02, 0, 0.32), lean=26, twist=-10, head_yaw=0,
                head_pitch=22)
        R.kneel(front=0.25, back_knee_x=0.0)
    else:
        R = Rig(k, "ally", twist=8)
        R.stance()
    R.body(pack=False)
    with Group(R.T, name="gear"):
        # carbine slung across the back
        with Group(M((-0.24, 0.05, 0.4), (0, 55, 0)), name="slung"):
            w_rifle(k, L=0.6, sl=0.4)
        # sling strap across the chest
        box("sling", (0.025, 0.05, 0.62), (0.185, -0.02, 0.4), k.webbing, rot=(38, 0, 0),
            bevel=0.005, outline=0.5)
    # satchel on the near hip with the emblem
    sat_c = R.hip + Vector((0.02, -0.27, 0.02))
    box("msatchel", (0.24, 0.12, 0.22), sat_c, C("#a79762"), bevel=0.04)
    box("mflap", (0.25, 0.125, 0.09), sat_c + Vector((0, -0.002, 0.07)), C("#968754"),
        bevel=0.03, outline=0.5)
    cross_patch("spatch", sat_c + Vector((0.0, -0.064, -0.02)), (0, 0, -90), 0.1,
                C(OLIVE_PATCH), C(WHITE), rim=C(WHITE))
    rod("mstrap", R.tp((0.0, 0.2, 0.68)), sat_c + Vector((0, 0.02, 0.1)), 0.02, k.webbing,
        outline=0.5)
    with Group(R.H, name="head"):
        R.face()
        R.ally_helmet(emblem=True)
    bandage = C(WHITE)
    if pose == "attack":
        hn = Vector((0.56, -0.18, 0.2))
        hf = Vector((0.46, 0.1, 0.32))
        S, E = R.arm(-1, hn, pole=(0, -1, -0.4))
        R.arm(1, hf, pole=(-0.3, 0.6, -1))
        rod("bandage", hn + Vector((0.03, -0.05, -0.05)), hn + Vector((0.03, 0.09, -0.05)),
            0.055, bandage, verts=16)
        tube("btail", [hn + Vector((0.05, 0.0, -0.08)), hn + Vector((0.12, 0.02, -0.15)),
                       hn + Vector((0.16, 0.02, -0.18))], 0.018, bandage, outline=0.5)
        mz = hn
    else:
        hn = Vector((0.18, -0.3, 0.66))
        S, E = R.arm(-1, hn, pole=(-0.4, -0.5, -1))
        R.arm(1, Vector((0.1, 0.32, 0.62)), pole=(-0.4, 0.6, -1))
        rod("bandage", hn + Vector((0.06, -0.06, 0.0)), hn + Vector((0.06, 0.06, 0.0)), 0.05,
            bandage, verts=16)
        mz = hn
    armband(R, S, E, k)
    return mz


def build_sniper(pose):
    k = ally_kit()
    if pose == "attack":
        R = aim_rig(k, "ally", hip=(-0.04, 0, 0.53))
        R.stance(-0.18, 0.18)
    else:
        R = Rig(k, "ally")
        R.stance()
    R.body(pack=False)
    with Group(R.H, name="head"):
        R.face()
        R.ghillie()
    with Group(R.T, name="cape"):
        rng = random.Random(9)
        cols = [C("#4d5a2c"), C("#6b6a3a"), C("#3f4a24"), C("#7a6d45")]
        for i in range(22):
            y = rng.uniform(-0.26, 0.26)
            z = rng.uniform(0.45, 0.72)
            p0 = Vector((-0.17, y, z))
            rod("cstrip", p0, p0 + Vector((-rng.uniform(0.05, 0.12), y * 0.3,
                                           -rng.uniform(0.15, 0.3))),
                rng.uniform(0.03, 0.045), rng.choice(cols), r2=0.006, verts=6, outline=0.45,
                smooth=False)
    return rifle_poses(R, pose, k, L=0.9, sl=0.46, scope=True, wood=C("#5e3d22"))


def build_mg(pose):
    k = ally_kit()
    if pose == "attack":
        R = Rig(k, "ally", hip=(-0.04, 0, 0.53), lean=-6, twist=30, head_yaw=5)
        R.stance(-0.2, 0.17)
        W = M((0.16, -0.28, 0.80), (0, -4, 0))
    else:
        R = Rig(k, "ally", twist=10)
        R.stance(-0.1, 0.1)
        W = M((0.14, -0.28, 0.76), (0, -32, 0))
    R.body()
    with Group(R.T, name="bandolier"):
        box("bando", (0.03, 0.07, 0.72), (0.19, 0.0, 0.40), C(BRASS), rot=(-38, 0, 0),
            bevel=0.01, outline=0.6)
        box("ammobox", (0.16, 0.12, 0.14), (0.0, -0.3, 0.06), C("#4f5a2a"), bevel=0.02)
    with Group(R.H, name="head"):
        R.face(brow=True)
        R.ally_helmet()
    with Group(W, name="mg"):
        g = w_mg(k)
    R.arm(-1, place(W, g["grip"]), pole=(-0.4, -0.8, -1))
    R.arm(1, place(W, g["fore"] if pose == "attack" else g["top"]), pole=(-0.2, 0.4, -1))
    return place(W, g["muzzle"])


def build_sapper(pose):
    k = ally_kit()
    if pose == "attack":
        R = Rig(k, "ally", hip=(-0.02, 0, 0.54), lean=-10, twist=38, head_yaw=-5,
                head_pitch=-6)
        R.stance(-0.2, 0.17)
    else:
        R = Rig(k, "ally", twist=10)
        R.stance()
    R.body(pack=False)
    with Group(R.T, name="charges"):
        with Group(M((-0.27, 0.0, 0.42), (0, 0, 90)), name="backcharge"):
            box("bc", (0.4, 0.16, 0.3), (0, 0, 0), C("#a79762"), bevel=0.04)
            box("bcb", (0.42, 0.17, 0.05), (0, 0, 0.06), C("#6b5d3a"), bevel=0.01, outline=0.5)
        box("hipcharge", (0.18, 0.1, 0.15), (0.06, -0.3, 0.06), C("#a79762"), bevel=0.03)
        box("hipband", (0.04, 0.11, 0.16), (0.08, -0.3, 0.06), C("#6b5d3a"), bevel=0.005,
            outline=0.5)
        # pliers / wire roll
        rod("wire", (-0.05, -0.27, 0.0), (-0.05, -0.33, 0.0), 0.06, C("#7a5a32"), verts=14,
            outline=0.6)
    with Group(R.H, name="head"):
        R.face(brow=True)
        R.ally_helmet(band="#2f3418")
    if pose == "attack":
        hn = Vector((-0.44, -0.33, 1.52))
        R.arm(-1, hn, pole=(0.3, -0.8, -1))
        with Group(M(hn + Vector((-0.02, -0.05, 0.05)), (0, -30, 0)), name="throwsatchel"):
            w_satchel(k)
        W = M((0.28, 0.12, 0.92), (0, 12, 0))
        with Group(W, name="shotgun"):
            g = w_shotgun(k)
        R.arm(1, place(W, g["grip"]), pole=(-0.4, 0.4, -1))
        return hn
    W = M((0.18, -0.26, 0.82), (0, -50, 0))
    with Group(W, name="shotgun"):
        g = w_shotgun(k)
    R.arm(-1, place(W, g["grip"]), pole=(-0.3, -0.6, -1))
    R.arm(1, place(W, g["fore"]), pole=(-0.2, 0.2, -1))
    return place(W, g["muzzle"])


# ---- Vossmark -----------------------------------------------------------
def build_e_rifleman(pose):
    k = enemy_kit()
    if pose == "attack":
        R = aim_rig(k, "enemy")
        R.stance(-0.17, 0.17)
    else:
        R = Rig(k, "enemy")
        R.stance()
    R.body()
    with Group(R.T, name="kit"):
        rod("canister", (-0.2, 0.12, 0.08), (-0.2, 0.12, 0.34), 0.07, C("#5a5d52"), verts=14)
        box("breadbag", (0.12, 0.08, 0.14), (-0.12, -0.27, 0.08), C("#6a6650"), bevel=0.03,
            outline=0.7)
    with Group(R.H, name="head"):
        R.mask()
        R.enemy_helmet()
    return rifle_poses(R, pose, k, wood=k.wood)


def build_e_grenadier(pose):
    k = enemy_kit()
    if pose == "attack":
        R = Rig(k, "enemy", hip=(-0.02, 0, 0.54), lean=-10, twist=38, head_yaw=-5,
                head_pitch=-6)
        R.stance(-0.2, 0.17)
    else:
        R = Rig(k, "enemy", twist=8)
        R.stance()
    R.body()
    with Group(R.T, name="sticks"):
        for i, (y, a) in enumerate([(-0.14, -12), (-0.02, 4), (0.1, 16)]):
            with Group(M((0.2, y, 0.07), (0, -78 + a * 0.3, a)), name="beltstick"):
                w_stick(k)
        for y in (-0.18, 0.0, 0.18):
            box("gbag", (0.08, 0.1, 0.14), (-0.21, y, 0.12), C("#5a5d52"), bevel=0.02,
                outline=0.6)
    with Group(R.H, name="head"):
        R.mask()
        R.enemy_helmet()
    if pose == "attack":
        hn = Vector((-0.44, -0.33, 1.5))
        R.arm(-1, hn, pole=(0.3, -0.8, -1))
        with Group(M(hn, (0, -110, 0)), name="throwstick"):
            g = w_stick(k)
        R.arm(1, Vector((0.48, 0.12, 1.12)), pole=(-0.3, 0.4, -1))
        return hn
    hn = Vector((0.16, -0.3, 0.62))
    R.arm(-1, hn, pole=(-0.4, -0.5, -1))
    with Group(M(hn + Vector((-0.07, 0, 0)), (0, -60, 0)), name="heldstick"):
        w_stick(k)
    R.arm(1, Vector((0.06, 0.33, 0.62)), pole=(-0.4, 0.6, -1))
    return hn


def build_e_flamer(pose):
    k = enemy_kit()
    if pose == "attack":
        R = Rig(k, "enemy", hip=(-0.03, 0, 0.53), lean=6, twist=30, head_yaw=5)
        R.stance(-0.19, 0.17)
        W = M((0.2, -0.3, 0.86), (0, -2, 0))
    else:
        R = Rig(k, "enemy", twist=8)
        R.stance()
        W = M((0.2, -0.3, 0.74), (0, 28, 0))
    R.body()
    tankm = C("#5f5f4c")
    with Group(R.T, name="tanks"):
        for s in (-1, 1):
            capsule("ftank", (-0.33, s * 0.13, 0.12), (-0.33, s * 0.13, 0.62), 0.13, 0.13,
                    tankm, segs=20)
            rod("fband", (-0.33, s * 0.13, 0.25), (-0.33, s * 0.13, 0.29), 0.14, C("#8a4b2a"),
                verts=20, outline=0.5)
        rod("fpipe", (-0.33, -0.15, 0.02), (-0.33, 0.15, 0.02), 0.04, k.metal)
        rod("fvalve", (-0.33, 0.0, 0.66), (-0.33, 0.0, 0.76), 0.035, k.metal, outline=0.6)
        box("harness", (0.03, 0.06, 0.6), (0.185, -0.13, 0.42), k.belt, bevel=0.01,
            outline=0.5)
    with Group(R.H, name="head"):
        R.mask()
        R.enemy_helmet()
    with Group(W, name="nozzle"):
        g = w_nozzle(k)
    R.arm(-1, place(W, g["grip"]), pole=(-0.4, -0.8, -1))
    R.arm(1, place(W, g["fore"]), pole=(-0.2, 0.3, -1))
    # hose from the tanks' bottom pipe to the wand
    p0 = R.tp((-0.33, -0.16, 0.02))
    p3 = place(W, g["rear"])
    tube("hose", [p0, p0 + Vector((0.0, -0.08, -0.22)), p3 + Vector((-0.2, -0.04, -0.15)),
                  p3], 0.035, C("#2f302c"))
    return place(W, g["muzzle"])


def build_e_ski(pose):
    white = "#e6e8e2"
    k = enemy_kit(coat=white, coat_dark="#cfd2cb", trousers="#d9dcd5", helmet=white,
                  belt="#5a5d52", shin="#d9dcd5", rubber="#55584f", hand="#cfd2cb")
    lift = 0.045
    if pose == "attack":
        R = aim_rig(k, "enemy", hip=(-0.02, 0, 0.55 + lift))
        R.leg(-1, -0.14, lift=lift)
        R.leg(1, 0.14, lift=lift)
    else:
        R = Rig(k, "enemy", hip=(0, 0, HIP_Z + lift), lean=8)
        R.leg(-1, -0.08, lift=lift)
        R.leg(1, 0.08, lift=lift)
    skim = C("#7a5232")
    for s, x in ((-1, -0.03), (1, 0.03)):
        y = s * 0.12
        box("ski", (1.12, 0.09, 0.035), (x, y, 0.0175), skim, bevel=0.01, outline=0.8)
        box("skitip", (0.16, 0.09, 0.03), (x + 0.62, y, 0.05), skim, rot=(0, -30, 0),
            bevel=0.01, outline=0.8)
        box("binding", (0.12, 0.1, 0.03), (x - 0.02, y, 0.05), k.belt, bevel=0.005,
            outline=0.5)
    R.body(coat_len=0.28)
    with Group(R.H, name="head"):
        R.mask()
        # snow hood instead of a helmet
        dome("shood", 0.32, (-0.02, 0, 0.0), k.helmet, scale=(1.0, 1.0, 1.05))
        lathe("shoodside", [(0.30, 0.02), (0.335, 0.02), (0.36, -0.34), (0.32, -0.35),
                            (0.27, 0.0)], k.helmet, a0=58, a1=302, segs=28, loc=(-0.02, 0, 0))
        lathe("sfur", [(0.30, 0.0), (0.345, 0.0), (0.345, 0.05), (0.30, 0.05)],
                  C("#b9b2a0"), a0=-62, a1=62, segs=24, loc=(-0.02, 0, 0.0), rot=(0, -20, 0),
              outline=0.6)
    if pose == "attack":
        return rifle_poses(R, pose, k, L=0.6, sl=0.42, wood=k.wood)
    # idle: carbine slung on the back, ski poles planted
    with Group(R.T, name="slung"):
        with Group(M((-0.24, 0.05, 0.4), (0, 60, 0)), name="sl"):
            w_rifle(k, L=0.6, sl=0.42, wood=k.wood)
    pm = C("#3b3d38")
    for s, hx, fx in ((-1, 0.24, 0.42), (1, 0.18, 0.36)):
        hand = Vector((hx, s * 0.3, 0.7))
        R.arm(s, hand, pole=(-0.4, s * 0.6, -1))
        rod("pole", hand + Vector((0, 0, 0.1)), (fx, s * 0.33, 0.0), 0.016, pm, verts=8,
            outline=0.6)
        rod("basket", (fx - 0.01, s * 0.33, 0.07), (fx - 0.005, s * 0.33, 0.085), 0.05, pm,
            verts=12, outline=0.5)
    return None


def build_e_mortar(pose):
    k = enemy_kit()
    R = Rig(k, "enemy", hip=(-0.08, 0, 0.32), lean=18 if pose == "attack" else 6,
            twist=-5, head_yaw=0, head_pitch=10 if pose == "attack" else 0)
    R.kneel(front=0.16, back_knee_x=-0.08)
    R.body(coat_len=0.08, coat_open=True)
    with Group(R.T, name="kit"):
        box("rbag", (0.12, 0.12, 0.16), (-0.12, -0.27, 0.08), C("#6a6650"), bevel=0.03,
            outline=0.7)
    with Group(R.H, name="head"):
        R.mask()
        R.enemy_helmet()
    # the mortar beside him
    tube_m = C("#4a5046")
    base = Vector((0.5, 0.05, 0.05))
    ang = 62
    d = Vector((math.cos(rad(ang)), 0, math.sin(rad(ang))))
    mouth = base + d * 0.74
    box("plate", (0.34, 0.34, 0.05), (0.5, 0.05, 0.025), k.metal, bevel=0.01)
    sphere("breech", 0.08, base + Vector((0, 0, 0.04)), k.metal)
    rod("tube", base, mouth, 0.07, tube_m, verts=20)
    rod("muzzlering", mouth - d * 0.04, mouth, 0.082, k.metal, verts=20, outline=0.6)
    collar = base + d * 0.5
    for s in (-1, 1):
        rod("bipod", collar, Vector((0.95, 0.05 + s * 0.2, 0.0)), 0.02, k.metal, outline=0.6)
        box("bfoot", (0.06, 0.05, 0.02), (0.95, 0.05 + s * 0.2, 0.01), k.metal, bevel=0,
            outline=0.5)
    rod("screw", collar, Vector((0.92, 0.05, 0.16)), 0.018, k.metal, outline=0.6)
    box("msight", (0.06, 0.04, 0.07), collar + Vector((-0.02, -0.09, 0.02)), C("#2f302c"),
        bevel=0.01, outline=0.5)
    if pose == "attack":
        rnd = mouth + Vector((0, 0, 0.14))
        with Group(M(rnd, (0, 180, 0)), name="round"):
            mortar_round("mround", k)
        R.arm(-1, rnd + Vector((-0.03, -0.07, 0.02)), pole=(-0.2, -0.6, -1))
        R.arm(1, rnd + Vector((-0.03, 0.07, 0.04)), pole=(-0.2, 0.6, -1))
        return mouth
    rnd = R.tp((0.32, -0.02, 0.32))
    with Group(M(rnd, (0, 0, 0)), name="round"):
        mortar_round("mround", k)
    R.arm(-1, rnd + Vector((0.0, -0.07, -0.02)), pole=(-0.3, -0.8, -1))
    R.arm(1, rnd + Vector((0.0, 0.07, 0.02)), pole=(-0.3, 0.8, -1))
    # spare rounds in a crate
    box("rcrate", (0.22, 0.16, 0.12), (-0.5, 0.2, 0.06), C("#6b5338"), bevel=0.02)
    return mouth


def build_e_officer(pose):
    k = enemy_kit(coat="#50554e", coat_dark="#3f433d", trousers="#4a4e47")
    if pose == "attack":
        R = Rig(k, "enemy", hip=(-0.02, 0, 0.55), lean=-3, twist=25, head_yaw=10)
        R.stance(-0.15, 0.15)
    else:
        R = Rig(k, "enemy", lean=-3, twist=5)
        R.stance(-0.1, 0.1)
    R.body(coat_len=0.18)
    with Group(R.T, name="kit"):
        box("holster", (0.14, 0.07, 0.12), (0.02, -0.27, 0.1), C("#3f3328"), bevel=0.02,
            outline=0.7)
        box("crossbelt", (0.025, 0.05, 0.66), (0.185, 0.0, 0.42), k.belt, rot=(-36, 0, 0),
            bevel=0.005, outline=0.5)
        for s in (-1, 1):
            box("tab", (0.02, 0.07, 0.05), (0.13, s * 0.12, 0.69), C("#8a7a4a"), bevel=0,
                outline=0.0)
    with Group(R.H, name="head"):
        sk = C("#dcb48e")
        sphere("head", 0.28, (0, 0, 0), sk, scale=(1.0, 0.95, 1.0), segs=28, rings=14)
        for az in (-32, 32):
            sphere("eye", 0.034, sph(0.262, az, 0), C(ALLY["eye"]), scale=(0.7, 0.8, 1.1),
                   rot=(0, 0, az), outline=0.0)
        box("brow", (0.05, 0.14, 0.035), sph(0.27, -32, 12), C("#2a2622"), rot=(0, -20, -32),
            bevel=0.01, outline=0.0)
        sphere("nose", 0.055, sph(0.27, -6, -12), sk, outline=0.6)
        sphere("ear", 0.065, sph(0.255, -92, -6), sk, scale=(0.6, 1, 1), outline=0.6)
        box("mouth", (0.03, 0.1, 0.02), sph(0.265, -12, -32), C("#5a3a2a"), rot=(0, 0, -12),
            bevel=0, outline=0.0)
        # monocle-free stern face; peaked cap
        cap = C("#3f433d")
        with Group(M((-0.01, 0, 0.16), (0, -12, 0)), name="cap"):
            lathe("crown", [(0.002, 0.2), (0.33, 0.22), (0.35, 0.19), (0.28, 0.1),
                            (0.27, 0.0), (0.002, 0.0)], cap, segs=36, scale=(1.08, 1, 1))
            lathe("capband", [(0.27, 0.0), (0.29, 0.0), (0.29, 0.09), (0.27, 0.09)],
                  C("#2a2c27"), segs=36, scale=(1.08, 1, 1), outline=0.0)
            lathe("visor", [(0.26, 0.01), (0.39, -0.025), (0.39, -0.05), (0.26, -0.015)],
                  C("#1f1f1c"), a0=-70, a1=70, segs=30)
            # fictional cap badge: khaki hexagon with a rust slit
            cyl("capemb", 0.05, 0.03, sph(0.3, -12, 0) + Vector((0, 0, 0.14)), C("#c9b98a"),
                verts=6, rot=(0, 90, -12), smooth=False, outline=0.5)
            box("capslit", (0.03, 0.035, 0.035), sph(0.316, -12, 0) + Vector((0, 0, 0.14)),
                C("#8a4b2a"), rot=(45, 0, -12), bevel=0, outline=0.0)
    W = None
    if pose == "attack":
        Sn = R.shoulder(-1)
        hn = Vector((Sn.x + 0.52, -0.34, Sn.z + 0.08))
        R.arm(-1, hn, pole=(0, -0.5, -1))
        W = M(hn, (0, -4, 0))
        R.arm(1, R.tp((-0.2, 0.2, 0.22)), pole=(-0.2, 0.6, -1))
    else:
        hn = Vector((0.12, -0.32, 0.58))
        R.arm(-1, hn, pole=(-0.3, -0.5, -1))
        W = M(hn, (0, 62, 0))
        R.arm(1, R.tp((-0.2, 0.18, 0.25)), pole=(-0.2, 0.6, -1))
    W = W @ M(s=1.4)
    with Group(W, name="pistol"):
        g = w_pistol(k)
    return W @ g["muzzle"]


def build_e_shock(pose):
    k = enemy_kit(coat="#4a4f47", coat_dark="#3a3e37", helmet="#3e423b", crest="#2f322d",
                  trousers="#3f433c")
    iron = C("#353832")
    if pose == "attack":
        R = Rig(k, "enemy", hip=(-0.02, 0, 0.55), lean=-8, twist=20, head_yaw=0,
                head_pitch=-4, broad=1.25)
        R.stance(-0.2, 0.18)
    else:
        R = Rig(k, "enemy", lean=6, twist=12, broad=1.25)
        R.stance(-0.12, 0.12)
    R.body(coat_len=0.22)
    with Group(R.T, name="armour"):
        box("plate", (0.08, 0.46, 0.46), (0.2, 0, 0.42), iron, bevel=0.04)
        for y in (-0.18, 0.18):
            for z in (0.24, 0.6):
                sphere("rivet", 0.022, (0.245, y, z), C("#5a5d55"), outline=0.0)
        # small caged lantern on the chest plate
        rod("lantern", (0.25, 0, 0.36), (0.25, 0, 0.5), 0.05, C(MINT, True), verts=12,
            outline=0.0)
        for y in (-0.03, 0.03):
            box("lbar", (0.02, 0.012, 0.16), (0.3, y, 0.43), iron, bevel=0, outline=0.4)
        box("lcap", (0.1, 0.12, 0.03), (0.27, 0, 0.52), iron, bevel=0.005, outline=0.5)
        for s in (-1, 1):
            sphere("pauldron", 0.17, (0.0, s * 0.31, 0.6), iron, scale=(1.0, 0.8, 0.75))
    with Group(R.H, name="head"):
        R.mask(lens_hex=MINT, emissive=True)
        R.enemy_helmet()
    if pose == "attack":
        hn = Vector((-0.06, -0.26, 1.64))
        hf = Vector((0.06, -0.12, 1.6))
        R.arm(-1, hn, pole=(0.3, -1, -0.5))
        R.arm(1, hf, pole=(0.3, 0.8, -0.5))
        W = M(hn + Vector((0.05, 0, 0.0)), (0, -172, 0))
    else:
        hn = Vector((0.2, -0.34, 0.6))
        R.arm(-1, hn, pole=(-0.3, -0.6, -1))
        R.arm(1, Vector((0.08, 0.34, 0.62)), pole=(-0.3, 0.6, -1))
        W = M(hn + Vector((-0.05, 0, 0)), (0, -38, 0))
    with Group(W, name="club"):
        g = w_club(k)
    return W @ g["tip"]


# --------------------------------------------------------------------------
# the field tent (static)
# --------------------------------------------------------------------------
def build_tent(pose):
    canvas = C("#8f8a5c")
    fly = C("#6b7040")
    dark = C("#2a2820")
    wood = C("#8a6a3f")
    wood2 = C("#6f5332")
    khaki = C("#b3a26f")
    rope = C("#c2b48a")
    with Group(M((0.15, 0, 0), (0, 0, -18)), name="tentg"):
        prof = [(-1.25, 0.0), (1.25, 0.0), (1.25, 0.42), (0.0, 1.72), (-1.25, 0.42)]
        prism("tent", prof, -0.95, 0.95, canvas, bevel=0.05)
        # roof fly
        for s in (-1, 1):
            ang = math.degrees(math.atan2(1.3, 1.25))
            box("fly", (1.88, 2.06, 0.05), (s * 0.64, 0, 1.1), fly,
                rot=(0, s * ang, 0), bevel=0.02)
        rod("ridge", (0, -1.08, 1.79), (0, 1.08, 1.79), 0.05, wood2)
        rod("pole", (0, -1.0, 0), (0, -1.0, 1.86), 0.04, wood2)
        # door: dark opening with tied-back flaps
        prism("door", [(-0.45, 0.0), (0.45, 0.0), (0.0, 1.15)], -0.97, -0.955, dark,
              bevel=0.0, outline=0.0)
        for s in (-1, 1):
            rod("flap", (s * 0.46, -0.99, 0.05), (s * 0.12, -0.99, 1.1), 0.05, khaki,
                r2=0.025, verts=10)
        # gable patch: white cross on olive
        cross_patch("gpatch", (0.0, -0.97, 1.36), (0, 0, -90), 0.28, C(OLIVE_PATCH),
                    C(WHITE), rim=C(WHITE))
        # guy ropes + pegs
        for s in (-1, 1):
            for y in (-0.8, 0.8):
                rod("rope", (s * 1.25, y, 0.42), (s * 1.7, y, 0.0), 0.012, rope, verts=6,
                    outline=0.5)
                rod("peg", (s * 1.7, y, 0.0), (s * 1.7, y, 0.1), 0.02, wood2, verts=6,
                    outline=0.5)
    # crates on the left
    def crate(name, size, loc, rot=0):
        box(name, size, loc, wood, rot=(0, 0, rot), bevel=0.03)
        for dz in (-0.3, 0.3):
            box(name + "_slat", (size[0] + 0.01, size[1] + 0.01, 0.04),
                (loc[0], loc[1], loc[2] + dz * size[2]), wood2, rot=(0, 0, rot), bevel=0.0,
                outline=0.0)
    crate("crate1", (0.6, 0.55, 0.45), (-1.85, -0.25, 0.225), rot=-12)
    crate("crate2", (0.48, 0.45, 0.36), (-1.9, -0.25, 0.63), rot=6)
    cross_patch("cpatch", (-1.86, -0.53, 0.225), (0, 0, -100), 0.2, C(OLIVE_PATCH), C(WHITE))
    crate("crate3", (0.42, 0.4, 0.32), (-1.3, -0.75, 0.16), rot=20)
    # flag pole with the medical flag
    fx, fy = 1.85, 0.25
    rod("fpole", (fx, fy, 0), (fx, fy, 2.25), 0.03, wood2, verts=10)
    sphere("ftop", 0.05, (fx, fy, 2.27), C("#c4993e"), outline=0.6)
    flag = C(OLIVE_PATCH)
    bm_pts = []
    with Group(M((fx + 0.02, fy - 0.03, 1.95), (0, 0, -12)), name="flagg"):
        # gently waving flag as a few tilted panels
        for i in range(4):
            x = 0.09 + i * 0.17
            box("flag", (0.18, 0.025, 0.42), (x, 0.03 * math.sin(i * 1.6), 0), flag,
                rot=(0, 0, 10 * math.cos(i * 1.6)), bevel=0.0, outline=0.8)
        box("fcv", (0.1, 0.04, 0.3), (0.34, -0.012, 0.0), C(WHITE), bevel=0, outline=0.0)
        box("fch", (0.3, 0.04, 0.1), (0.34, -0.012, 0.0), C(WHITE), bevel=0, outline=0.0)
    # stretcher on short legs in front
    sx0, sx1, sy = 0.55, 2.15, -1.25
    for dy in (-0.2, 0.2):
        rod("spole", (sx0, sy + dy, 0.16), (sx1, sy + dy, 0.16), 0.03, wood, verts=10)
        for x in (sx0 + 0.25, sx1 - 0.25):
            rod("sleg", (x, sy + dy, 0.0), (x, sy + dy, 0.16), 0.022, wood2, verts=8,
                outline=0.6)
    box("scanvas", (1.15, 0.38, 0.03), ((sx0 + sx1) / 2, sy, 0.17), khaki, bevel=0.01)
    box("blanket", (0.6, 0.4, 0.07), ((sx0 + sx1) / 2 - 0.15, sy, 0.21), C("#6b7040"),
        bevel=0.03)
    rod("pillow", (sx0 + 0.32, sy - 0.15, 0.22), (sx0 + 0.32, sy + 0.15, 0.22), 0.06,
        C(WHITE), verts=12)
    # bucket / lantern detail
    rod("bucket", (-1.2, -1.05, 0.0), (-1.2, -1.05, 0.22), 0.11, C("#5a5e55"), r2=0.13,
        verts=16)
    return None


# --------------------------------------------------------------------------
# the Lantern Colossus (tight-cropped like the vehicles)
# --------------------------------------------------------------------------
def build_colossus():
    rs.Ctx.outline = 0.085
    hullm = toon("co_hull", rs.RELIC, [(0.6, "#353a33")], patch_scale=0.8)
    plate = toon("co_plate", "#4a5047")
    iron = toon("co_iron", "#2f302c")
    bronze = toon("co_bronze", "#7a5a32")
    rust = toon("co_rust", "#8a4b2a")
    rivet = toon("co_rivet", "#5d6157")
    rune = toon("co_rune", MINT, emissive=True)
    core = toon("co_core", "#c9ffe4", emissive=True)
    flame = toon("co_flame", MINT, emissive=True)
    chain_m = toon("co_chain", "#5d574a")

    def leg(y, sx, near):
        hip = Vector((sx - 0.05, y, 3.3))
        knee = Vector((sx + 0.6, y, 2.0))
        ankle = Vector((sx - 0.05, y, 0.62))
        rod("thigh", hip, knee, 0.42, plate, r2=0.34, verts=10, smooth=False)
        rod("shin", knee, ankle, 0.34, plate, r2=0.27, verts=10, smooth=False)
        cyl("knee", 0.42, 0.75, knee, bronze if near else iron, axis="Y", verts=20, bevel=0.05)
        cyl("kneecap", 0.2, 0.1, knee + Vector((0, -0.42, 0)), iron, axis="Y", verts=12)
        rod("piston", hip + Vector((-0.35, -0.3 * (1 if near else -1) * 0, 0.0)),
            ankle + Vector((-0.3, 0, 0.3)), 0.07, iron, verts=10)
        cyl("ankle", 0.3, 0.62, ankle, iron, axis="Y", verts=16, bevel=0.04)
        # foot: wedge with three toes
        prism("foot", [(sx - 0.75, 0.0), (sx + 0.85, 0.0), (sx + 0.95, 0.18),
                       (sx + 0.5, 0.5), (sx - 0.5, 0.55), (sx - 0.8, 0.3)],
              y - 0.42, y + 0.42, plate, bevel=0.06)
        for t in (-0.25, 0.0, 0.25):
            prism("toe", [(sx + 0.8, 0.0), (sx + 1.22, 0.0), (sx + 1.1, 0.2), (sx + 0.8, 0.28)],
                  y + t - 0.1, y + t + 0.1, iron, bevel=0.03)
        if near:
            for i in range(4):
                cyl("frivet", 0.045, 0.05, (sx - 0.55 + i * 0.35, y - 0.44, 0.3), rivet,
                    axis="Y", verts=10, outline=0.0)

    leg(0.65, -0.45, False)
    leg(-0.65, 0.3, True)
    lift = Group(M((0, 0, 0.8)), name="upper")
    lift.__enter__()

    # hull: a riveted iron boiler-chest, leaning forward
    prof = [(-1.25, 2.35), (0.95, 2.3), (1.45, 2.85), (1.5, 3.9), (1.1, 4.55),
            (-0.9, 4.6), (-1.4, 4.1), (-1.5, 2.9)]
    prism("hull", prof, -0.95, 0.95, hullm, bevel=0.1, seg=3)
    prism("sideplate", [(-1.2, 2.5), (0.9, 2.45), (1.3, 2.9), (1.3, 3.85), (0.95, 4.35),
                        (-0.8, 4.4), (-1.25, 4.0), (-1.3, 2.95)], -1.02, -0.94, plate,
          bevel=0.04)
    # rivet rows around the side plate
    for i in range(9):
        x = -1.05 + i * 0.27
        for z in (2.62, 4.25):
            cyl("rivet", 0.045, 0.05, (x, -1.04, z), rivet, axis="Y", verts=10, outline=0.0)
    for z in (2.95, 3.35, 3.75):
        for x in (-1.18, 1.2):
            cyl("rivet", 0.045, 0.05, (x, -1.04, z), rivet, axis="Y", verts=10, outline=0.0)
    # bronze belly band with runes
    box("band", (2.5, 0.06, 0.32), (-0.05, -1.05, 2.82), bronze, bevel=0.02, outline=0.6)
    rs.rune_row("co_r1", -1.0, 0.95, 2.82, 0.22, -1.085, rune, start=2, gap=0.75)
    # caged lantern core in the chest
    cx, cz = 0.15, 3.55
    cyl("corering", 0.62, 0.16, (cx, -1.06, cz), bronze, axis="Y", verts=32, bevel=0.03)
    cyl("corewell", 0.5, 0.1, (cx, -1.08, cz), iron, axis="Y", verts=32, outline=0.0)
    sphere("core", 0.46, (cx, -1.05, cz), flame, scale=(1, 0.75, 1.1), outline=0.0)
    sphere("coreflame", 0.26, (cx, -1.3, cz - 0.04), core, scale=(1, 0.5, 1.5), outline=0.0)
    for i in range(3):
        x = cx - 0.25 + i * 0.25
        h = math.sqrt(max(0.0, 0.52 ** 2 - (x - cx) ** 2)) * 2
        box("cagebar", (0.05, 0.05, h), (x, -1.47, cz), iron, bevel=0.0, outline=0.4)
    # runes above the core
    rs.rune_row("co_r2", -0.85, 1.05, 4.12, 0.24, -1.05, rune, start=5, gap=0.6)
    # head: squat riveted dome with a glowing visor slit
    lathe("head", [(0.002, 0.8), (0.35, 0.78), (0.62, 0.55), (0.7, 0.2), (0.7, 0.0),
                   (0.002, 0.0)], plate, segs=28, loc=(0.45, 0, 4.45))
    lathe("visor", [(0.6, 0.3), (0.72, 0.3), (0.72, 0.4), (0.6, 0.4)], rune, a0=-80, a1=20,
          segs=28, loc=(0.45, 0, 4.45), outline=0.0)
    lathe("brow", [(0.62, 0.42), (0.8, 0.44), (0.8, 0.52), (0.6, 0.55)], iron, a0=-85,
          a1=25, segs=28, loc=(0.45, 0, 4.45))
    sphere("crown", 0.12, (0.45, 0, 5.27), rust)
    # stacks + chains on the back
    for i, (x, y) in enumerate(((-1.05, 0.45), (-0.75, 0.62))):
        cyl("stack", 0.17, 0.8, (x, y, 4.7), iron, verts=12, bevel=0.03)
        cyl("stackcap", 0.21, 0.12, (x, y, 5.12), rust, verts=12, bevel=0.02)
    rs.chain("co_ch", rs.catenary((-1.3, 4.3), (-1.35, 2.7), -0.15), 0.2, chain_m, -0.98)
    # far arm: heavy fist hanging behind the hull
    rod("farupper", (-0.4, 1.15, 4.1), (-0.65, 1.2, 3.0), 0.3, plate, verts=10, smooth=False)
    rod("farfore", (-0.65, 1.2, 3.0), (-0.3, 1.2, 2.1), 0.26, plate, verts=10, smooth=False)
    box("fist", (0.6, 0.55, 0.55), (-0.25, 1.2, 1.9), iron, bevel=0.1)
    sphere("farshoulder", 0.48, (-0.4, 1.1, 4.1), iron)
    # near arm: the cannon
    sh = Vector((-1.0, -1.3, 3.95))
    el = Vector((-0.85, -1.42, 2.75))
    sphere("shoulder", 0.55, sh, plate)
    box("pauldron", (1.2, 0.9, 0.25), sh + Vector((0, 0, 0.42)), iron, rot=(0, -8, 0),
        bevel=0.08)
    rs.rune_row("co_r3", sh.x - 0.4, sh.x + 0.45, sh.z + 0.42, 0.16, sh.y - 0.46, rune,
                start=1, gap=0.6)
    rod("upperarm", sh, el, 0.3, plate, verts=10, smooth=False)
    sphere("elbow", 0.36, el, bronze)
    gz = el.z - 0.15
    box("breech", (1.0, 0.7, 0.7), (el.x + 0.15, el.y, gz), plate, bevel=0.1, seg=3)
    cyl("barrel", 0.26, 2.4, (el.x + 1.6, el.y, gz), iron, axis="X", verts=24)
    cyl("bring", 0.31, 0.14, (el.x + 1.0, el.y, gz), rune, axis="X", verts=24, outline=0.5)
    cyl("bring2", 0.31, 0.14, (el.x + 1.85, el.y, gz), bronze, axis="X", verts=24,
        outline=0.5)
    cyl("cmuzzle", 0.33, 0.5, (el.x + 2.95, el.y, gz), iron, axis="X", r2=0.39, verts=24,
        bevel=0.03)
    for i in range(3):
        cyl("cvent", 0.07, 0.05, (el.x + 2.85 + i * 0.13, el.y - 0.38, gz), C("#1b1a14"),
            axis="Y", verts=10, outline=0.0)
    lift.__exit__()
    return Vector((el.x + 3.2, el.y, gz + 0.8))


FIGS = {
    "rifleman": build_rifleman,
    "mg": build_mg,
    "medic": build_medic,
    "sniper": build_sniper,
    "sapper": build_sapper,
    "veteran": build_veteran,
    "tent": build_tent,
    "e_rifleman": build_e_rifleman,
    "e_grenadier": build_e_grenadier,
    "e_flamer": build_e_flamer,
    "e_ski": build_e_ski,
    "e_mortar": build_e_mortar,
    "e_officer": build_e_officer,
    "e_shock": build_e_shock,
}
ORDER = list(FIGS) + ["colossus"]
STATIC = {"tent"}
SCALE = {"e_shock": 1.1}
GLOW = {"e_shock": (3.0, 0.85), "colossus": (9, 0.8)}


# --------------------------------------------------------------------------
# render + post
# --------------------------------------------------------------------------
def fixed_camera(sc, cw, ch):
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam_data.clip_start = 0.1
    cam_data.clip_end = 200
    cam_data.ortho_scale = max(cw, ch) / PPU
    cam = bpy.data.objects.new("Cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    rot = Matrix.Rotation(rad(90 - TILT), 3, "X")
    cam.rotation_euler = rot.to_euler()
    up = rot @ Vector((0, 1, 0))
    view = rot @ Vector((0, 0, -1))
    centre = up * ((BASE - ch / 2) / PPU)     # world origin lands on (cw/2, BASE)
    cam.location = centre - view * 60
    sc.render.resolution_x = cw * SS
    sc.render.resolution_y = ch * SS
    bpy.context.view_layer.update()
    return cam


def project(sc, cam, p):
    from bpy_extras.object_utils import world_to_camera_view
    co = world_to_camera_view(sc, cam, p)
    return co.x, 1 - co.y


def render_raw(sc, path):
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)


def save_png(img, path, limit_kb):
    img.save(path, optimize=True)
    if os.path.getsize(path) > limit_kb * 1024:
        q = img.quantize(colors=256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        q.save(path, optimize=True)


def render_figure(name, pose, tmp):
    rs.Ctx.objects = []
    rs._MAT_CACHE.clear()
    Group.stack = []
    sc = rs.reset_scene()
    sc.cycles.samples = SAMPLES
    rs.Ctx.outline = FIG_OUTLINE
    s = SCALE.get(name, 1.0)
    root_m = M((0, 0, 0), (0, 0, FIG_YAW if name != "tent" else 0), s)
    with Group(root_m, name="root"):
        mz = FIGS[name](pose)
    cw, ch = (512, 256) if name == "tent" else (256, 256)
    cam = fixed_camera(sc, cw, ch)
    raw = os.path.join(tmp, f"{name}_{pose}.png")
    render_raw(sc, raw)
    img = Image.open(raw).convert("RGBA").resize((cw, ch), Image.LANCZOS)
    if name in GLOW:
        img = rs.add_glow(img, GLOW[name][0], GLOW[name][1])
    # snap the soles onto the baseline
    a = img.split()[3].point(lambda v: 255 if v > 110 else 0)
    bb = a.getbbox()
    shift = (BASE - 1) - (bb[3] - 1)
    if abs(shift) > 8:
        print(f"[units] WARNING {name}_{pose}: baseline shift {shift}px", flush=True)
    out = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    out.paste(img, (0, shift))
    bb2 = out.split()[3].point(lambda v: 255 if v > 10 else 0).getbbox()
    if bb2 and (bb2[0] <= 0 or bb2[1] <= 0 or bb2[2] >= cw):
        print(f"[units] WARNING {name}_{pose}: touches the canvas edge {bb2}", flush=True)
    fn = f"{name}_{pose}.png"
    save_png(out, os.path.join(OUT_DIR, fn), 78 if name == "tent" else 39)
    muzzle = None
    if mz is not None:
        u, v = project(sc, cam, root_m @ Vector(mz))
        muzzle = [round(u, 4), round((v * ch + shift) / ch, 4)]
    return fn, muzzle, (cw, ch), shift, bb2


def render_colossus(tmp):
    rs.Ctx.objects = []
    rs._MAT_CACHE.clear()
    Group.stack = []
    sc = rs.reset_scene()
    sc.cycles.samples = 12
    with Group(M((0, 0, 0), (0, 0, -22)), name="root"):
        mz = build_colossus()
    bpy.context.view_layer.update()
    cam = rs.setup_camera(sc)
    raw = os.path.join(tmp, "colossus_raw.png")
    render_raw(sc, raw)
    mx, my = rs.project(sc, cam, M((0, 0, 0), (0, 0, -22)) @ mz)
    img = Image.open(raw).convert("RGBA")
    alpha = img.split()[3]
    bbox = alpha.point(lambda v: 255 if v > 10 else 0).getbbox()
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    s = (rs.FINAL_LONG - 2 * rs.PAD) / bw if bw >= bh else (rs.FINAL_LONG - rs.PAD) / bh
    img = rs.add_glow(img, GLOW["colossus"][0] / s, GLOW["colossus"][1])
    crop = img.crop(bbox)
    tw, th = max(1, round(bw * s)), max(1, round(bh * s))
    crop = crop.resize((tw, th), Image.LANCZOS)
    W, H = tw + 2 * rs.PAD, th + rs.PAD
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(crop, (rs.PAD, rs.PAD))
    fn = "colossus_idle.png"
    save_png(out, os.path.join(OUT_DIR, fn), 245)
    muzzle = [round(((mx - x0) * s + rs.PAD) / W, 4), round(((my - y0) * s + rs.PAD) / H, 4)]
    return fn, muzzle, (W, H)


def contact_sheet(path):
    names = [n for n in ORDER if n != "colossus"]
    tiles = []
    for n in names:
        for p in ("idle", "attack"):
            f = os.path.join(OUT_DIR, f"{n}_{p}.png")
            if os.path.exists(f):
                tiles.append((f"{n}/{p}", Image.open(f).convert("RGBA")))
    cols = 8
    rows = []
    row, wsum = [], 0
    for t in tiles:
        if wsum + t[1].width > cols * 256 and row:
            rows.append(row)
            row, wsum = [], 0
        row.append(t)
        wsum += t[1].width
    if row:
        rows.append(row)
    W = cols * 256
    H = len(rows) * 270
    sheet = Image.new("RGBA", (W, H), (214, 208, 190, 255))
    d = ImageDraw.Draw(sheet)
    for ri, row in enumerate(rows):
        x = 0
        y = ri * 270
        for label, im in row:
            d.rectangle([x, y, x + im.width - 1, y + 255], outline=(170, 164, 150))
            sheet.alpha_composite(im, (x, y))
            d.line([x, y + BASE, x + im.width - 1, y + BASE], fill=(220, 40, 40), width=1)
            d.line([x + im.width // 2, y + BASE - 6, x + im.width // 2, y + BASE + 6],
                   fill=(40, 40, 220), width=1)
            d.text((x + 4, y + 256), label, fill=(20, 20, 20))
            x += im.width
    sheet.save(path)
    return path


def main():
    args = sys.argv[1:]
    if "--" in args:
        args = args[args.index("--") + 1:]
    sheet = None
    for a in list(args):
        if a.startswith("--sheet="):
            sheet = a.split("=", 1)[1]
            args.remove(a)
    names = [a for a in args if a in ORDER] or list(ORDER)
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "units.json")
    meta = {}
    if os.path.exists(json_path):
        try:
            with open(json_path) as f:
                meta = json.load(f)
        except Exception:
            meta = {}
    tmp = tempfile.mkdtemp(prefix="units_raw_")
    t0 = time.time()
    try:
        for n in names:
            t1 = time.time()
            if n == "colossus":
                fn, mz, size = render_colossus(tmp)
                meta[n] = {"idle": fn, "attack": None, "canvas": list(size), "muzzle": mz}
                print(f"[units] colossus {size} muzzle={mz} ({time.time() - t1:.1f}s)",
                      flush=True)
                continue
            entry = {"idle": None, "attack": None, "canvas": None, "muzzle": None}
            for pose in (("idle",) if n in STATIC else ("idle", "attack")):
                fn, mz, size, shift, bb = render_figure(n, pose, tmp)
                entry[pose] = fn
                entry["canvas"] = list(size)
                if pose == "attack":
                    entry["muzzle"] = mz
                print(f"[units] {n}_{pose}: shift={shift} bbox={bb} muzzle={mz}", flush=True)
            meta[n] = entry
            print(f"[units] {n} ({time.time() - t1:.1f}s)", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    meta = {k: meta[k] for k in ORDER if k in meta}
    with open(json_path, "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    if sheet:
        contact_sheet(sheet)
        print(f"[units] contact sheet -> {sheet}")
    print(f"[units] done in {time.time() - t0:.1f}s -> {OUT_DIR}")


if __name__ == "__main__":
    main()
