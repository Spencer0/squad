"""Procedural low-poly toon sprites for the Vossmark war machines.

Run (from the repo root):
    /tmp/claude-0/blendenv/bin/python tools/blender/render_sprites.py [name ...]

Builds every model from primitives with bmesh, shades it with an
emission-only toon shader (fixed key light from the upper left, soft
fill, banded with a constant colour ramp), outlines it with an inverted
hull (solidify + dark backface material), renders it side-on with an
orthographic Cycles camera onto a transparent film, then crops and
downscales with Pillow and writes assets/sprites/*.png + sprites.json.

Everything is fictional: no real insignia, no replicas of real vehicles.
"""
import json
import math
import os
import sys
import time

import bpy  # noqa: E402  (must precede bmesh/mathutils)
import bmesh
from mathutils import Matrix, Vector
from mathutils.geometry import convex_hull_2d
from PIL import Image, ImageChops, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(ROOT, "assets", "sprites")
TMP_DIR = os.path.join(OUT_DIR, ".render_tmp")

RENDER_LONG = 1400      # px, long side of the raw render
FINAL_LONG = 640        # px, long side of the final sprite
PAD = 4                 # px padding (top/left/right; bottom is ground contact)
TILT = 7.0              # degrees of downward camera tilt
SAMPLES = 24

# Key light (upper left, slightly toward the camera). Shading is computed
# in the shader from this direction, so the bands are crisp and noise free.
KEY = Vector((-0.5, -0.62, 0.78)).normalized()
# Brightness bands: (threshold on N.L, multiplier). Below the first threshold
# is the fill/shadow band.
BANDS = [(-2.0, 0.58), (0.0, 0.80), (0.30, 1.0), (0.66, 1.16)]

OUTLINE_HEX = "#1b1a14"
MINT = "#6dffb4"


# --------------------------------------------------------------------------
# colour helpers
# --------------------------------------------------------------------------
def srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hexcol(h, a=1.0):
    h = h.lstrip("#")
    return tuple(srgb_to_lin(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4)) + (a,)


# --------------------------------------------------------------------------
# scene
# --------------------------------------------------------------------------
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = SAMPLES
    sc.cycles.use_adaptive_sampling = False
    sc.cycles.use_denoising = False
    sc.cycles.max_bounces = 2
    sc.cycles.diffuse_bounces = 0
    sc.cycles.glossy_bounces = 0
    sc.cycles.transmission_bounces = 0
    sc.cycles.transparent_max_bounces = 16
    sc.render.film_transparent = True
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.image_settings.color_depth = "8"
    sc.render.resolution_percentage = 100
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.render.threads_mode = "AUTO"
    world = bpy.data.worlds.new("World")
    world.color = (0, 0, 0)
    sc.world = world
    return sc


# --------------------------------------------------------------------------
# materials
# --------------------------------------------------------------------------
_MAT_CACHE = {}


def _sock(sockets, ident):
    for s in sockets:
        if s.identifier == ident:
            return s
    raise KeyError(ident)


def toon(name, base, patches=None, patch_scale=1.3, emissive=False, bands=None):
    """Emission-only toon material.

    base: hex colour. patches: list of (threshold, hex) for flat camo blobs
    driven by object-space noise.  emissive: flat unshaded colour (runes).
    """
    key = (name,)
    if key in _MAT_CACHE:
        return _MAT_CACHE[key]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    if emissive:
        em.inputs["Color"].default_value = hexcol(base)
        em.inputs["Strength"].default_value = 1.0
        _MAT_CACHE[key] = m
        return m

    # base colour (optionally camo)
    if patches:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = patch_scale
        noise.inputs["Detail"].default_value = 0.0
        noise.inputs["Roughness"].default_value = 0.4
        nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
        ramp_c = nt.nodes.new("ShaderNodeValToRGB")
        ramp_c.color_ramp.interpolation = "CONSTANT"
        els = ramp_c.color_ramp.elements
        els[0].position = 0.0
        els[0].color = hexcol(base)
        els[1].position = patches[0][0]
        els[1].color = hexcol(patches[0][1])
        for thr, col in patches[1:]:
            e = els.new(thr)
            e.color = hexcol(col)
        nt.links.new(noise.outputs["Fac"], ramp_c.inputs["Fac"])
        base_out = ramp_c.outputs["Color"]
    else:
        rgb = nt.nodes.new("ShaderNodeRGB")
        rgb.outputs[0].default_value = hexcol(base)
        base_out = rgb.outputs[0]

    # lighting factor = banded(N . KEY)
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    dot = nt.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = KEY
    nt.links.new(geo.outputs["Normal"], dot.inputs[0])
    # remap -1..1 -> 0..1 for the ramp
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -1.0
    mr.inputs["From Max"].default_value = 1.0
    nt.links.new(dot.outputs["Value"], mr.inputs["Value"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    bl = bands or BANDS
    els = ramp.color_ramp.elements
    els[0].position = 0.0
    v = bl[0][1]
    els[0].color = (v, v, v, 1)
    els[1].position = (bl[1][0] + 1) / 2
    v = bl[1][1]
    els[1].color = (v, v, v, 1)
    for thr, val in bl[2:]:
        e = els.new((thr + 1) / 2)
        e.color = (val, val, val, 1)
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])

    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    _sock(mix.inputs, "Factor_Float").default_value = 1.0
    nt.links.new(base_out, _sock(mix.inputs, "A_Color"))
    nt.links.new(ramp.outputs["Color"], _sock(mix.inputs, "B_Color"))
    nt.links.new(_sock(mix.outputs, "Result_Color"), em.inputs["Color"])
    em.inputs["Strength"].default_value = 1.0
    _MAT_CACHE[key] = m
    return m


def outline_mat():
    key = ("__outline",)
    if key in _MAT_CACHE:
        return _MAT_CACHE[key]
    m = bpy.data.materials.new("Outline")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = hexcol(OUTLINE_HEX)
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    # hull normals are flipped: faces toward the camera report backfacing
    # -> transparent; the far shell peeking past the silhouette is dark.
    nt.links.new(geo.outputs["Backfacing"], mix.inputs[0])
    nt.links.new(em.outputs[0], mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    _MAT_CACHE[key] = m
    return m


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------
class Ctx:
    outline = 0.06      # world-unit hull thickness, set per sprite
    objects = []


def _finish(bm, name, mat, loc=(0, 0, 0), rot=(0, 0, 0), smooth=False,
            bevel=0.0, seg=2, outline=1.0, sharp_angle=40.0):
    me = bpy.data.meshes.new(name)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
        try:
            me.set_sharp_from_angle(angle=math.radians(sharp_angle))
        except Exception:
            pass
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = [math.radians(a) for a in rot]
    me.materials.append(mat)
    if bevel > 0:
        b = ob.modifiers.new("bevel", "BEVEL")
        b.width = bevel
        b.segments = seg
        b.limit_method = "ANGLE"
        b.angle_limit = math.radians(35)
        b.harden_normals = False
    if outline and Ctx.outline > 0:
        me.materials.append(outline_mat())
        s = ob.modifiers.new("outline", "SOLIDIFY")
        s.thickness = Ctx.outline * outline
        s.offset = 1.0
        s.use_flip_normals = True
        s.use_even_offset = True
        s.use_rim = False
        s.material_offset = 1
    Ctx.objects.append(ob)
    return ob


def box(name, size, loc, mat, rot=(0, 0, 0), bevel=0.04, seg=2, outline=1.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    return _finish(bm, name, mat, loc, rot, bevel=bevel, seg=seg, outline=outline)


def cyl(name, r, depth, loc, mat, axis="Z", r2=None, verts=24, rot=None,
        bevel=0.0, seg=2, outline=1.0, smooth=True, caps=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=caps, cap_tris=False, segments=verts,
                          radius1=r, radius2=r if r2 is None else r2, depth=depth)
    if rot is None:
        rot = {"Z": (0, 0, 0), "X": (0, 90, 0), "Y": (90, 0, 0), "-X": (0, -90, 0)}[axis]
    return _finish(bm, name, mat, loc, rot, smooth=smooth, bevel=bevel, seg=seg,
                   outline=outline)


def sphere(name, r, loc, mat, scale=(1, 1, 1), rot=(0, 0, 0), segs=24, rings=12,
           outline=1.0):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=r)
    bmesh.ops.scale(bm, vec=Vector(scale), verts=bm.verts)
    return _finish(bm, name, mat, loc, rot, smooth=True, outline=outline,
                   sharp_angle=80)


def prism(name, pts, y0, y1, mat, bevel=0.05, seg=2, outline=1.0, loc=(0, 0, 0),
          smooth=False):
    """Extrude an XZ side profile (list of (x, z), any winding) from y0 to y1."""
    bm = bmesh.new()
    front = [bm.verts.new((x, y0, z)) for x, z in pts]
    back = [bm.verts.new((x, y1, z)) for x, z in pts]
    bm.faces.new(front)
    bm.faces.new(list(reversed(back)))
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((front[i], front[j], back[j], back[i]))
    return _finish(bm, name, mat, loc, bevel=bevel, seg=seg, outline=outline,
                   smooth=smooth)


def circles_hull(circles, n=40):
    """Convex hull (XZ) of a set of circles -> list of points (track belt)."""
    pts = []
    for (cx, cz, r) in circles:
        for i in range(n):
            a = 2 * math.pi * i / n
            pts.append((cx + r * math.cos(a), cz + r * math.sin(a)))
    idx = convex_hull_2d(pts)
    return [pts[i] for i in idx]


def ring_prism(name, outer, inner, y0, y1, mat, outline=1.0):
    """Extruded ring between two closed XZ loops with equal point counts."""
    bm = bmesh.new()
    n = len(outer)
    of = [bm.verts.new((x, y0, z)) for x, z in outer]
    ob_ = [bm.verts.new((x, y1, z)) for x, z in outer]
    inf = [bm.verts.new((x, y0, z)) for x, z in inner]
    inb = [bm.verts.new((x, y1, z)) for x, z in inner]
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((of[i], of[j], inf[j], inf[i]))
        bm.faces.new((ob_[j], ob_[i], inb[i], inb[j]))
        bm.faces.new((of[j], of[i], ob_[i], ob_[j]))
        bm.faces.new((inf[i], inf[j], inb[j], inb[i]))
    return _finish(bm, name, mat, outline=outline, smooth=False)


def seg_box(name, p0, p1, width, depth, y, mat, outline=0.0):
    """Thin bar in the XZ plane from p0 to p1 (for runes, struts)."""
    dx, dz = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dz)
    ang = math.degrees(math.atan2(dz, dx))
    c = ((p0[0] + p1[0]) / 2, y, (p0[1] + p1[1]) / 2)
    return box(name, (length + width, depth, width), c, mat, rot=(0, -ang, 0),
               bevel=0.0, outline=outline)


def chain(name, pts, link_len, mat, y, link_r=None, wire=None, outline=0.45):
    """Chain of torus links along an XZ polyline, alternating orientation."""
    link_r = link_r or link_len * 0.55
    wire = wire or link_len * 0.17
    # resample polyline
    segs = []
    total = 0
    for a, b in zip(pts[:-1], pts[1:]):
        l = math.hypot(b[0] - a[0], b[1] - a[1])
        segs.append((a, b, l))
        total += l
    count = max(2, int(total / link_len))
    out = []
    for k in range(count + 1):
        d = total * k / count
        for a, b, l in segs:
            if d <= l or (a, b, l) == segs[-1]:
                t = min(1.0, d / l) if l else 0
                p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                ang = math.atan2(b[1] - a[1], b[0] - a[0])
                break
            d -= l
        out.append((p, ang))
    obs = []
    for k, (p, ang) in enumerate(out):
        bm = bmesh.new()
        # torus: ring in local XY plane, elongated along local X
        major_segs, minor_segs = 14, 6
        verts = []
        for i in range(major_segs):
            u = 2 * math.pi * i / major_segs
            row = []
            for j in range(minor_segs):
                v = 2 * math.pi * j / minor_segs
                rr = link_r * 0.5 + wire * math.cos(v)
                x = rr * math.cos(u) * 1.45
                yy = rr * math.sin(u)
                z = wire * math.sin(v)
                row.append(bm.verts.new((x, yy, z)))
            verts.append(row)
        for i in range(major_segs):
            for j in range(minor_segs):
                a = verts[i][j]
                b = verts[(i + 1) % major_segs][j]
                c = verts[(i + 1) % major_segs][(j + 1) % minor_segs]
                d = verts[i][(j + 1) % minor_segs]
                bm.faces.new((a, b, c, d))
        # links alternate: one lies in the XZ plane (faces camera), next in XY
        roll = 90 if k % 2 == 0 else 0
        rot = (roll, -math.degrees(ang), 0)
        obs.append(_finish(bm, f"{name}_{k}", mat, (p[0], y, p[1]), rot,
                           smooth=True, outline=outline, sharp_angle=89))
    return obs


def catenary(p0, p1, sag, n=12):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = p0[0] + (p1[0] - p0[0]) * t
        z = p0[1] + (p1[1] - p0[1]) * t - sag * 4 * t * (1 - t)
        pts.append((x, z))
    return pts


# Fictional "Lantern Bureau" glyphs: original shapes built from strokes in a
# unit cell (x 0..0.6, z 0..1).  Deliberately not letters and not historical
# runes.  A zero-length stroke is a dot.
def _poly(pts, closed=True):
    segs = list(zip(pts[:-1], pts[1:]))
    if closed:
        segs.append((pts[-1], pts[0]))
    return segs


def _ngon(cx, cz, r, n, phase=0.0):
    return [(cx + r * math.cos(phase + 2 * math.pi * i / n),
             cz + r * math.sin(phase + 2 * math.pi * i / n)) for i in range(n)]


DOT = lambda x, z: ((x, z), (x, z))  # noqa: E731
RUNES = [
    # lantern: hexagon on a stem with a hanging ring tick
    _poly(_ngon(0.3, 0.55, 0.24, 6, math.pi / 6)) + [((0.3, 0.0), (0.3, 0.31)),
                                                      ((0.3, 0.79), (0.3, 1.0))],
    # watching eye: diamond with a pupil dot and a lash
    _poly([(0.0, 0.5), (0.3, 0.8), (0.6, 0.5), (0.3, 0.2)]) + [DOT(0.3, 0.5),
                                                               ((0.3, 0.8), (0.3, 1.0))],
    # hook and dot
    [((0.12, 0.0), (0.12, 1.0)), ((0.12, 1.0), (0.5, 1.0)), ((0.5, 1.0), (0.5, 0.62)),
     DOT(0.45, 0.22)],
    # barred cup
    [((0.08, 1.0), (0.08, 0.35)), ((0.08, 0.35), (0.3, 0.08)), ((0.3, 0.08), (0.52, 0.35)),
     ((0.52, 0.35), (0.52, 1.0)), ((-0.04, 0.62), (0.64, 0.62))],
    # inverted triangle on a spike
    _poly([(0.0, 1.0), (0.6, 1.0), (0.3, 0.48)]) + [((0.3, 0.48), (0.3, 0.0)),
                                                     DOT(0.3, 0.82)],
    # crescent + bar
    [((0.5, 0.95), (0.2, 0.8)), ((0.2, 0.8), (0.1, 0.5)), ((0.1, 0.5), (0.2, 0.2)),
     ((0.2, 0.2), (0.5, 0.05)), ((0.36, 0.5), (0.62, 0.5))],
    # gate: two posts with a lintel and a hanging dot
    [((0.08, 0.0), (0.08, 0.85)), ((0.52, 0.0), (0.52, 0.85)), ((-0.02, 0.85), (0.62, 0.85)),
     DOT(0.3, 0.45)],
    # three stacked ticks on a spine
    [((0.3, 0.0), (0.3, 1.0)), ((0.3, 0.85), (0.55, 0.72)), ((0.3, 0.55), (0.05, 0.42)),
     ((0.3, 0.25), (0.55, 0.12))],
]


def rune_row(prefix, x0, x1, zc, height, y, mat, start=0, gap=0.35):
    """Etch a row of glowing runes on the XZ face at depth y."""
    w = 0.6 * height
    step = w + gap * height
    n = int((x1 - x0 + gap * height) / step)
    xs = x0 + ((x1 - x0) - (n * step - gap * height)) / 2
    stroke = height * 0.13
    for i in range(n):
        ox = xs + i * step
        if i % 4 == 3:      # separator dot between glyph groups
            c = (ox + w / 2, zc)
            seg_box(f"{prefix}_{i}_sep", c, c, stroke * 1.5, 0.04, y, mat)
            continue
        strokes = RUNES[(start + i * 5) % len(RUNES)]
        for k, (a, b) in enumerate(strokes):
            pa = (ox + a[0] * height, zc - height / 2 + a[1] * height)
            pb = (ox + b[0] * height, zc - height / 2 + b[1] * height)
            seg_box(f"{prefix}_{i}_{k}", pa, pb, stroke, 0.04, y, mat)


# --------------------------------------------------------------------------
# shared vehicle parts
# --------------------------------------------------------------------------
def tracks(prefix, circles, y_near, width, track_mat, wheel_mat, hub_mat,
           wheel_scale=0.86, wheels=True, far=True, teeth=True):
    belt = circles_hull(circles)
    for side, y in (("L", y_near), ("R", -y_near - width)):
        if side == "R" and not far:
            continue
        prism(f"{prefix}_track{side}", belt, y, y + width, track_mat, bevel=0.04)
    # tread teeth along the belt perimeter (near side)
    if teeth:
        n = len(belt)
        per = []
        tot = 0
        for i in range(n):
            a, b = belt[i], belt[(i + 1) % n]
            l = math.hypot(b[0] - a[0], b[1] - a[1])
            per.append((a, b, l))
            tot += l
        spacing = 0.34
        cnt = int(tot / spacing)
        d = 0
        idx = 0
        acc = 0
        for k in range(cnt):
            target = k * tot / cnt
            while acc + per[idx][2] < target:
                acc += per[idx][2]
                idx += 1
            a, b, l = per[idx]
            t = (target - acc) / l if l else 0
            px, pz = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            # outward normal (hull is CCW) = rotate tangent -90
            nx, nz = (b[1] - a[1]) / l, -(b[0] - a[0]) / l
            box(f"{prefix}_tooth{k}", (0.13, width * 0.96, 0.08),
                (px + nx * 0.02, y_near + width / 2, pz + nz * 0.02), track_mat,
                rot=(0, -ang, 0), bevel=0.0, outline=0.6)
    if wheels:
        for i, (cx, cz, r) in enumerate(circles):
            rw = r * wheel_scale
            cyl(f"{prefix}_wheel{i}", rw, 0.14, (cx, y_near - 0.05, cz), wheel_mat,
                axis="Y", verts=28, bevel=0.03)
            cyl(f"{prefix}_hub{i}", rw * 0.42, 0.06, (cx, y_near - 0.14, cz), hub_mat,
                axis="Y", verts=16, outline=0.6)
    return belt


# --------------------------------------------------------------------------
# models.  Each returns the muzzle tip world position.
# --------------------------------------------------------------------------
def emblem(name, loc, r, khaki, rust):
    """Fictional Vossmark mark: khaki hexagon plate with a rust lantern slit."""
    x, y, z = loc
    cyl(name, r, 0.04, loc, khaki, axis="Y", verts=6, rot=(90, 0, 0), smooth=False,
        outline=0.5)
    box(name + "_eye", (r * 0.62, 0.04, r * 0.62), (x, y - 0.03, z), rust,
        rot=(0, 45, 0), bevel=0.0, outline=0.0)
    box(name + "_pupil", (r * 0.2, 0.04, r * 0.2), (x, y - 0.05, z), khaki,
        rot=(0, 45, 0), bevel=0.0, outline=0.0)


FIELD_GREY = "#6d7268"
CAMO = [(0.52, "#4f554b"), (0.66, "#5e5a48")]


def build_tank():
    Ctx.outline = 0.065
    hull = toon("tank_hull", FIELD_GREY, CAMO, patch_scale=1.1)
    hull2 = toon("tank_turret", FIELD_GREY, CAMO, patch_scale=1.25)
    dark = toon("tank_track", "#34332d")
    wheel = toon("tank_wheel", "#5a5e55")
    hub = toon("tank_hub", "#3f423b")
    metal = toon("tank_metal", "#4a4d45")
    khaki = toon("tank_khaki", "#c9b98a")
    rust = toon("tank_rust", "#8a4b2a")

    circles = [(-2.15, 0.55, 0.42), (-1.32, 0.36, 0.36), (-0.47, 0.36, 0.36),
               (0.38, 0.36, 0.36), (1.23, 0.36, 0.36), (2.1, 0.62, 0.36)]
    tracks("t", circles, -1.35, 0.55, dark, wheel, hub)
    # hull with sloped glacis and rear plate
    prism("t_hull", [(-2.45, 0.78), (2.05, 0.78), (2.75, 1.22), (2.35, 1.62),
                     (-2.35, 1.62), (-2.55, 1.30)], -1.15, 1.15, hull, bevel=0.06)
    # track guards
    box("t_fender", (5.35, 0.62, 0.1), (0.12, -1.07, 1.03), metal, bevel=0.02)
    # tool box + exhaust
    box("t_toolbox", (0.9, 0.18, 0.28), (-1.4, -1.22, 1.24), metal, bevel=0.03)
    cyl("t_exhaust", 0.13, 0.55, (-2.55, -0.5, 1.15), metal, axis="X", bevel=0.02)
    cyl("t_light", 0.12, 0.16, (2.3, -0.85, 1.55), metal, axis="X", bevel=0.02)
    # oversized turret
    prism("t_turret", [(-1.55, 1.6), (1.15, 1.6), (1.4, 2.05), (1.0, 2.72),
                       (-1.25, 2.72), (-1.65, 2.25)], -1.0, 1.0, hull2, bevel=0.12, seg=3)
    box("t_bustle", (0.55, 1.5, 0.7), (-1.75, 0, 2.15), hull2, bevel=0.08)
    cyl("t_cupola", 0.36, 0.32, (-0.5, 0.05, 2.86), hull2, verts=20, bevel=0.05)
    cyl("t_hatch", 0.3, 0.08, (-0.5, 0.05, 3.06), metal, verts=20, bevel=0.02)
    emblem("t_emb", (-0.25, -1.02, 2.14), 0.3, khaki, rust)
    # mantlet + stubby barrel
    box("t_mantlet", (0.42, 0.9, 0.7), (1.38, 0, 2.1), metal, bevel=0.1, seg=3)
    cyl("t_barrel", 0.16, 1.35, (2.25, 0, 2.12), metal, axis="X", verts=20)
    cyl("t_brake", 0.23, 0.4, (2.98, 0, 2.12), metal, axis="X", verts=20, bevel=0.04)
    cyl("t_antenna", 0.025, 1.4, (-1.85, 0.6, 3.1), metal, verts=8, outline=0.6)
    return Vector((3.18, 0, 2.12))


RELIC = "#3e433c"


def build_relictank():
    Ctx.outline = 0.08
    hull = toon("rt_hull", RELIC, [(0.6, "#353a33")], patch_scale=0.9)
    turret_m = toon("rt_turret", "#464b43", [(0.62, "#3b4039")], patch_scale=1.1)
    plate = toon("rt_plate", "#4a5047")
    dark = toon("rt_track", "#2a2a26")
    wheel = toon("rt_wheel", "#4d5149")
    hub = toon("rt_hub", "#7a5a32")
    iron = toon("rt_iron", "#2f302c")
    chain_m = toon("rt_chain", "#5d574a")
    bronze = toon("rt_bronze", "#7a5a32")
    rust = toon("rt_rust", "#8a4b2a")
    rune = toon("rt_rune", MINT, emissive=True)
    core = toon("rt_core", "#c9ffe4", emissive=True)

    circles = [(-3.0, 0.68, 0.52), (-2.0, 0.45, 0.45), (-0.95, 0.45, 0.45),
               (0.1, 0.45, 0.45), (1.15, 0.45, 0.45), (2.2, 0.45, 0.45),
               (3.15, 0.8, 0.46)]
    tracks("r", circles, -1.75, 0.7, dark, wheel, hub)
    # massive hull
    prism("r_hull", [(-3.4, 0.95), (2.9, 0.95), (3.85, 1.5), (3.3, 2.2),
                     (-3.25, 2.2), (-3.55, 1.7)], -1.5, 1.5, hull, bevel=0.08)
    # armoured skirt covering the upper track run, with rivets
    prism("r_skirt", [(-3.45, 0.92), (3.05, 0.92), (3.45, 1.32), (3.25, 1.62),
                      (-3.35, 1.62), (-3.6, 1.32)], -1.95, -1.8, plate, bevel=0.04)
    for i in range(11):
        x = -3.1 + i * 0.62
        cyl(f"r_rivet{i}", 0.05, 0.05, (x, -1.97, 1.52), iron, axis="Y", verts=10,
            outline=0.0)
    # glowing etched groove + runes on the skirt
    box("r_groove", (6.2, 0.04, 0.05), (-0.15, -1.97, 1.03), rune, bevel=0, outline=0)
    rune_row("r_sr", -2.95, 2.85, 1.24, 0.26, -1.975, rune, start=1, gap=0.9)
    # front spikes on the glacis
    for i, z in enumerate((1.35, 1.75)):
        cyl(f"r_spike{i}", 0.13, 0.45, (3.75 - (z - 1.35) * 0.55 + 0.15, -0.9, z),
            iron, axis="X", r2=0.0, verts=10, rot=(0, 90, 0))
    # exhaust stacks
    cyl("r_exh", 0.16, 0.9, (-3.0, -0.9, 2.55), iron, verts=12, bevel=0.03)
    cyl("r_exh_cap", 0.2, 0.12, (-3.0, -0.9, 3.02), rust, verts=12, bevel=0.02)

    # turret: big, faceted, leaning forward
    prism("r_turret", [(-2.2, 2.25), (1.35, 2.25), (1.85, 2.8), (1.3, 3.62),
                       (-1.65, 3.62), (-2.35, 3.0)], -1.3, 1.3, turret_m,
          bevel=0.14, seg=3)
    box("r_bustle", (0.7, 1.9, 0.95), (-2.45, 0, 2.95), turret_m, bevel=0.1)
    # bronze band + runes around the turret
    box("r_band", (3.55, 0.06, 0.12), (-0.4, -1.31, 2.42), bronze, bevel=0.0,
        outline=0.5)
    rune_row("r_tr", -1.75, 1.0, 3.02, 0.36, -1.315, rune, start=4, gap=0.6)
    # mantlet, thick stubby barrel, rune ring, flared muzzle
    box("r_mantlet", (0.6, 1.3, 1.0), (1.9, 0, 2.95), iron, bevel=0.14, seg=3)
    cyl("r_barrel", 0.24, 1.8, (3.05, 0, 2.97), iron, axis="X", verts=24)
    cyl("r_ring", 0.29, 0.12, (2.6, 0, 2.97), rune, axis="X", verts=24, outline=0.5)
    cyl("r_ring2", 0.29, 0.12, (3.25, 0, 2.97), bronze, axis="X", verts=24, outline=0.5)
    cyl("r_muzzle", 0.3, 0.45, (4.1, 0, 2.97), iron, axis="X", r2=0.36, verts=24,
        bevel=0.03)

    # the Grave Lantern reliquary on the turret roof
    lx, lz = -0.25, 3.62
    cyl("r_lbase", 0.72, 0.22, (lx, 0, lz + 0.11), bronze, verts=8, bevel=0.04,
        rot=(0, 0, 22.5))
    cyl("r_lcore", 0.42, 1.05, (lx, 0, lz + 0.78), core, verts=16, outline=0.0)
    sphere("r_lflame", 0.3, (lx, 0, lz + 0.8), toon("rt_flame", MINT, emissive=True),
           scale=(1, 1, 1.5), outline=0.0)
    for i in range(4):
        a = math.radians(45 + 90 * i)
        cyl(f"r_lpost{i}", 0.07, 1.15, (lx + 0.52 * math.cos(a), 0.52 * math.sin(a),
                                        lz + 0.8), iron, verts=8)
    for i, xo in enumerate((-0.18, 0.18)):
        box(f"r_lbar{i}", (0.05, 0.05, 1.1), (lx + xo, -0.5, lz + 0.8), iron,
            bevel=0, outline=0.5)
    box("r_lmid", (1.05, 1.05, 0.08), (lx, 0, lz + 0.8), iron, bevel=0.01, outline=0.5)
    cyl("r_lroof", 0.78, 0.55, (lx, 0, lz + 1.63), iron, r2=0.12, verts=4,
        rot=(0, 0, 45), smooth=False, bevel=0.03)
    cyl("r_lcap", 0.6, 0.12, (lx, 0, lz + 1.38), bronze, verts=4, rot=(0, 0, 45),
        smooth=False, bevel=0.02)
    # ring handle
    bm = bmesh.new()
    bmesh.ops.create_circle(bm, cap_ends=False, segments=20, radius=0.26)
    handle_pts = [(lx + 0.26 * math.cos(2 * math.pi * i / 20),
                   lz + 2.15 + 0.26 * math.sin(2 * math.pi * i / 20)) for i in range(20)]
    bm.free()
    inner = [(lx + (p[0] - lx) * 0.62, lz + 2.15 + (p[1] - lz - 2.15) * 0.62)
             for p in handle_pts]
    ring_prism("r_lhandle", handle_pts, inner, -0.06, 0.06, iron)

    # chains: lantern to hull front, and swags along the turret side
    chain("r_ch1", catenary((lx + 0.55, lz + 1.3), (3.2, 2.2), 0.55), 0.22, chain_m,
          -0.75)
    chain("r_ch2", catenary((-2.2, 2.4), (-0.05, 2.4), 0.35), 0.2, chain_m, -1.38)
    chain("r_ch3", catenary((-0.05, 2.4), (1.5, 2.45), 0.3), 0.2, chain_m, -1.38)
    for i, x in enumerate((-2.2, -0.05, 1.5)):
        cyl(f"r_hook{i}", 0.09, 0.08, (x, -1.36, 2.42), rust, axis="Y", verts=10,
            outline=0.5)
    return Vector((4.33, 0, 2.97))


def build_armoredcar():
    Ctx.outline = 0.06
    body = toon("ac_body", FIELD_GREY, CAMO, patch_scale=1.2)
    tur = toon("ac_turret", FIELD_GREY, CAMO, patch_scale=1.5)
    tire = toon("ac_tire", "#2c2b27")
    hubm = toon("ac_hub", "#5a5e55")
    metal = toon("ac_metal", "#4a4d45")
    khaki = toon("ac_khaki", "#c9b98a")
    rust = toon("ac_rust", "#8a4b2a")
    slit = toon("ac_slit", "#141310")

    # body: faceted, angular, fictional design
    prism("ac_body", [(-2.35, 0.55), (2.05, 0.55), (2.55, 0.95), (2.3, 1.25),
                      (1.35, 1.75), (-1.75, 1.75), (-2.45, 1.2)], -1.05, 1.05, body,
          bevel=0.06)
    # mudguards over wheels
    for i, x in enumerate((-1.45, 1.4)):
        prism(f"ac_guard{i}", [(x - 0.8, 0.9), (x + 0.8, 0.9), (x + 0.68, 1.12),
                               (x - 0.68, 1.12)], -1.18, -1.02, metal, bevel=0.02)
    for i, x in enumerate((-1.45, 1.4)):
        for side, y in (("n", -1.12), ("f", 1.12)):
            cyl(f"ac_tire{i}{side}", 0.58, 0.42, (x, y, 0.58), tire, axis="Y",
                verts=32, bevel=0.1, seg=3)
            if side == "n":
                cyl(f"ac_hub{i}", 0.32, 0.1, (x, y - 0.2, 0.58), hubm, axis="Y",
                    verts=20, bevel=0.03)
                cyl(f"ac_cap{i}", 0.12, 0.08, (x, y - 0.27, 0.58), metal, axis="Y",
                    verts=12, outline=0.6)
    box("ac_visor", (0.1, 0.7, 0.12), (2.0, -0.3, 1.47), slit, rot=(0, -28, 0),
        bevel=0, outline=0.0)
    box("ac_door", (0.9, 0.05, 0.6), (-0.15, -1.06, 1.2), body, bevel=0.03, outline=0.5)
    cyl("ac_light", 0.12, 0.16, (2.35, -0.75, 1.22), metal, axis="X", bevel=0.02)
    cyl("ac_spare", 0.42, 0.22, (-2.5, 0, 1.25), tire, axis="X", verts=28, bevel=0.06)
    # emblem
    emblem("ac_emb", (-1.1, -1.07, 1.3), 0.24, khaki, rust)
    # small turret, autocannon
    prism("ac_turret", [(-0.95, 1.72), (0.8, 1.72), (0.98, 2.05), (0.6, 2.45),
                        (-0.75, 2.45), (-1.05, 2.1)], -0.75, 0.75, tur, bevel=0.1, seg=3)
    box("ac_mant", (0.3, 0.5, 0.42), (1.0, 0, 2.08), metal, bevel=0.07)
    cyl("ac_gun", 0.08, 1.5, (1.85, 0, 2.08), metal, axis="X", verts=14)
    cyl("ac_jacket", 0.12, 0.6, (1.45, 0, 2.08), metal, axis="X", verts=14)
    cyl("ac_flash", 0.12, 0.25, (2.65, 0, 2.08), metal, axis="X", verts=14, bevel=0.02)
    cyl("ac_antenna", 0.022, 1.2, (-1.85, 0.6, 2.35), metal, verts=8, outline=0.6)
    return Vector((2.78, 0, 2.08))


def build_bunker():
    Ctx.outline = 0.06
    conc = toon("bk_conc", "#9b9788", [(0.58, "#878377"), (0.7, "#a9a595")],
                patch_scale=1.6)
    conc2 = toon("bk_conc2", "#8f8b7d")
    sand = toon("bk_sand", "#8d7e52")
    sand2 = toon("bk_sand2", "#7f7149")
    slit = toon("bk_slit", "#141310", bands=[(-2, 1.0), (0, 1.0)])
    metal = toon("bk_metal", "#3f423b")
    rust = toon("bk_rust", "#8a4b2a")

    # rounded pillbox: squat cylinder with heavily rounded rim + dome roof
    cyl("bk_drum", 1.85, 1.35, (0, 0, 0.78), conc, verts=40, bevel=0.35, seg=4)
    sphere("bk_dome", 1.62, (0, 0, 1.3), conc, scale=(1, 1, 0.42), segs=40, rings=16)
    cyl("bk_cap", 0.45, 0.25, (-0.25, 0, 1.98), conc2, verts=20, bevel=0.08)
    cyl("bk_vent", 0.12, 0.35, (-0.25, 0, 2.2), metal, verts=12, outline=0.7)
    # firing slit on the front-right quadrant, MG pointing right (+X)
    ang = math.radians(-38)           # toward camera, right of centre
    r = 1.84
    sx, sy = r * math.cos(ang), r * math.sin(ang)
    box("bk_slit", (0.22, 1.05, 0.26), (sx, sy, 1.05), slit,
        rot=(0, 0, math.degrees(ang)), bevel=0.0, outline=0.0)
    box("bk_visor", (0.5, 1.4, 0.16), (sx * 1.04, sy * 1.04, 1.27), conc2,
        rot=(0, 0, math.degrees(ang)), bevel=0.05)
    box("bk_sill", (0.4, 1.3, 0.12), (sx * 1.02, sy * 1.02, 0.86), conc2,
        rot=(0, 0, math.degrees(ang)), bevel=0.04)
    # MG: perforated cooling jacket + thin barrel + bipod-free mount
    my = sy - 0.05
    cyl("bk_jacket", 0.11, 0.75, (sx + 0.35, my, 1.05), metal, axis="X", verts=14)
    cyl("bk_barrel", 0.05, 0.6, (sx + 0.95, my, 1.05), metal, axis="X", verts=10)
    cyl("bk_flash", 0.08, 0.16, (sx + 1.25, my, 1.05), metal, axis="X", verts=12)
    muzzle = Vector((sx + 1.33, my, 1.05))
    # rebar stub / rust stain detail
    # sandbag ring around the base (two staggered rows + a third partial)
    rows = [(0.0, 2.15, 34, 0.0), (0.27, 2.08, 34, 0.5), (0.54, 2.02, 30, 0.0)]
    for ri, (z, rad, n, off) in enumerate(rows):
        for i in range(n):
            a = 2 * math.pi * (i + off) / n
            x, y = rad * math.cos(a), rad * math.sin(a)
            if ri == 2 and not (-2.6 < a - 2 * math.pi < -0.95 or -2.6 < a < -0.95):
                continue   # third row only at the front-left, below the slit side
            m = sand if (i + ri) % 3 else sand2
            box(f"bk_bag{ri}_{i}", (0.42, 0.62, 0.3), (x, y, z + 0.15), m,
                rot=(0, 0, math.degrees(a) + 90 + ((i * 37) % 9 - 4)),
                bevel=0.12, seg=3, outline=0.8)
    return muzzle


def build_horror():
    Ctx.outline = 0.06
    robe = toon("h_robe", "#1d1c24", bands=[(-2, 0.75), (0, 0.95), (0.3, 1.15), (0.66, 1.45)])
    robe2 = toon("h_robe2", "#2a2833", bands=[(-2, 0.75), (0, 0.95), (0.3, 1.15), (0.66, 1.4)])
    mask = toon("h_mask", "#d9d4c3")
    tent = toon("h_tent", "#2e2b38", bands=[(-2, 0.75), (0, 0.95), (0.3, 1.15), (0.66, 1.4)])
    sucker = toon("h_sucker", "#8f8a9e")
    eye = toon("h_eye", MINT, emissive=True)
    bronze = toon("h_bronze", "#7a5a32")
    crack = toon("h_crack", "#3a3630")

    yaw = -30   # turn a little toward the camera so the mask reads
    # tentacles first (they sit under / behind the robe hem)
    tent_specs = [
        # (base x, base y, list of control points, base radius)
        ((0.6, -0.3), [(1.4, -0.5, 0.25), (2.2, -0.6, 0.05), (2.7, -0.6, 0.6), (2.4, -0.6, 1.0), (2.05, -0.6, 0.75)], 0.32),
        ((-0.6, -0.3), [(-1.4, -0.5, 0.2), (-2.2, -0.6, 0.15), (-2.55, -0.6, 0.7), (-2.25, -0.6, 1.05), (-1.95, -0.6, 0.85)], 0.3),
        ((0.3, -0.6), [(0.9, -1.0, 0.1), (1.5, -1.1, 0.0), (1.9, -1.2, 0.3), (1.7, -1.2, 0.55)], 0.26),
        ((-0.3, -0.6), [(-0.9, -1.0, 0.05), (-1.4, -1.1, 0.0), (-1.75, -1.2, 0.35), (-1.5, -1.2, 0.55)], 0.25),
        ((0.7, 0.4), [(1.6, 0.6, 0.6), (2.0, 0.7, 1.6), (1.7, 0.7, 2.2), (1.35, 0.7, 2.0)], 0.26),
        ((-0.7, 0.4), [(-1.5, 0.6, 0.7), (-1.9, 0.7, 1.7), (-1.6, 0.7, 2.35), (-1.25, 0.7, 2.15)], 0.25),
    ]
    for ti, (base, ctrl, r0) in enumerate(tent_specs):
        cu = bpy.data.curves.new(f"h_tc{ti}", "CURVE")
        cu.dimensions = "3D"
        cu.bevel_depth = r0
        cu.bevel_resolution = 3
        cu.resolution_u = 10
        cu.use_fill_caps = True
        sp = cu.splines.new("BEZIER")
        pts = [(base[0], base[1], 0.45)] + ctrl
        sp.bezier_points.add(len(pts) - 1)
        for k, p in enumerate(pts):
            bp = sp.bezier_points[k]
            bp.co = p
            bp.handle_left_type = bp.handle_right_type = "AUTO"
            bp.radius = max(0.12, 1.0 - k / (len(pts) - 1)) ** 0.9
        cob = bpy.data.objects.new(f"h_tcurve{ti}", cu)
        bpy.context.scene.collection.objects.link(cob)
        dg = bpy.context.evaluated_depsgraph_get()
        me = bpy.data.meshes.new_from_object(cob.evaluated_get(dg))
        bpy.data.objects.remove(cob)
        bm = bmesh.new()
        bm.from_mesh(me)
        bpy.data.meshes.remove(me)
        ob = _finish(bm, f"h_tent{ti}", tent, smooth=True, sharp_angle=80)
        ob.rotation_euler = (0, 0, math.radians(yaw))
        # a few suckers along the underside
        for k in range(1, len(ctrl)):
            px, py, pz = ctrl[k - 1]
            v = Matrix.Rotation(math.radians(yaw), 4, "Z") @ Vector((px, py - 0.18, pz))
            sphere(f"h_suck{ti}_{k}", 0.07 * (1.2 - k / len(ctrl)), v, sucker,
                   outline=0.0)

    # robe: tall flared cone with a rounded hem, plus shoulders
    rb = cyl("h_robe", 1.05, 3.4, (0, 0, 2.15), robe, r2=0.42, verts=28, bevel=0.15)
    rb.scale = (1.0, 0.82, 1.0)
    sphere("h_shoulders", 0.62, (0, 0, 3.75), robe, scale=(1.0, 0.85, 0.75))
    # hanging sleeve and a bronze hem band
    cyl("h_sleeve", 0.32, 1.5, (0.72, -0.2, 2.95), robe2, r2=0.2, verts=16,
        rot=(0, -16, 0), bevel=0.05)
    hem = cyl("h_hem", 1.07, 0.14, (0, 0, 0.62), bronze, verts=28, bevel=0.03)
    hem.scale = (1.0, 0.82, 1.0)
    # hood + porcelain mask, turned toward the viewer but facing right
    fyaw = -55
    rz = Matrix.Rotation(math.radians(fyaw), 4, "Z")
    fdir = rz @ Vector((1, 0, 0))
    side = rz @ Vector((0, 1, 0))
    head = Vector((0.12, 0, 4.4))
    sphere("h_hood", 0.66, head - fdir * 0.12, robe2, scale=(1.0, 1.0, 1.15))
    centre = head + fdir * 0.33
    mz, mu, mv = 0.3, 0.42, 0.56    # mask half-extents: depth, width, height
    sphere("h_mask", 1.0, centre, mask, scale=(mz, mu, mv), rot=(0, 0, fyaw),
           segs=28, rings=14)
    eyes = [(-0.17, 0.2, 0.095), (0.16, 0.22, 0.095), (0.0, 0.0, 0.085),
            (-0.26, -0.1, 0.06), (0.24, -0.08, 0.065), (-0.06, -0.3, 0.055),
            (0.08, 0.42, 0.05)]
    for i, (u, v, r) in enumerate(eyes):
        d = mz * math.sqrt(max(0.0, 1 - (u / mu) ** 2 - (v / mv) ** 2))
        pos = centre + side * u + Vector((0, 0, v)) + fdir * (d - r * 0.35)
        sphere(f"h_eye{i}", r, pos, eye, segs=12, rings=6, outline=0.0)
    # dark eye sockets behind the glowing pupils for contrast
    for i, (u, v, r) in enumerate(eyes):
        d = mz * math.sqrt(max(0.0, 1 - (u / mu) ** 2 - (v / mv) ** 2))
        pos = centre + side * u + Vector((0, 0, v)) + fdir * (d - r * 1.15)
        sphere(f"h_sock{i}", r * 1.4, pos, crack, segs=12, rings=6, outline=0.0)
    # broken halo behind the head
    halo = []
    for i in range(29):
        a = math.radians(-20 + i * 9.5)
        halo.append((0.0 + 0.95 * math.cos(a), 4.45 + 0.95 * math.sin(a)))
    inner = [(x * 0.84, 4.45 + (z - 4.45) * 0.84) for x, z in halo]
    bm = bmesh.new()
    n = len(halo)
    y0, y1 = 0.55, 0.65
    of = [bm.verts.new((x, y0, z)) for x, z in halo]
    ob_ = [bm.verts.new((x, y1, z)) for x, z in halo]
    inf = [bm.verts.new((x, y0, z)) for x, z in inner]
    inb = [bm.verts.new((x, y1, z)) for x, z in inner]
    for i in range(n - 1):
        j = i + 1
        bm.faces.new((of[i], of[j], inf[j], inf[i]))
        bm.faces.new((ob_[j], ob_[i], inb[i], inb[j]))
        bm.faces.new((of[j], of[i], ob_[i], ob_[j]))
        bm.faces.new((inf[i], inf[j], inb[j], inb[i]))
    bm.faces.new((of[0], inf[0], inb[0], ob_[0]))
    bm.faces.new((of[-1], ob_[-1], inb[-1], inf[-1]))
    _finish(bm, "h_halo", bronze)
    return centre + fdir * mz


MODELS = {
    "tank": build_tank,
    "relictank": build_relictank,
    "armoredcar": build_armoredcar,
    "bunker": build_bunker,
    "horror": build_horror,
}


# --------------------------------------------------------------------------
# camera, render, post
# --------------------------------------------------------------------------
def setup_camera(sc):
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "ORTHO"
    cam_data.clip_start = 0.1
    cam_data.clip_end = 400
    cam = bpy.data.objects.new("Cam", cam_data)
    sc.collection.objects.link(cam)
    sc.camera = cam
    rot = Matrix.Rotation(math.radians(90 - TILT), 3, "X")
    cam.rotation_euler = rot.to_euler()
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    inv = rot.inverted()
    xs, ys = [], []
    for ob in Ctx.objects:
        ev = ob.evaluated_get(dg)
        mw = ob.matrix_world
        for c in ev.bound_box:
            p = inv @ (mw @ Vector(c))
            xs.append(p.x)
            ys.append(p.y)
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = x1 - x0, y1 - y0
    m = 0.05 * max(w, h)
    W, H = w + 2 * m, h + 2 * m
    cam_data.ortho_scale = max(W, H)
    if W >= H:
        sc.render.resolution_x = RENDER_LONG
        sc.render.resolution_y = int(round(RENDER_LONG * H / W))
    else:
        sc.render.resolution_y = RENDER_LONG
        sc.render.resolution_x = int(round(RENDER_LONG * W / H))
    centre = rot @ Vector(((x0 + x1) / 2, (y0 + y1) / 2, 0))
    view = rot @ Vector((0, 0, -1))
    cam.location = centre - view * 150
    bpy.context.view_layer.update()
    return cam


def project(sc, cam, p):
    from bpy_extras.object_utils import world_to_camera_view
    co = world_to_camera_view(sc, cam, p)
    return co.x * sc.render.resolution_x, (1 - co.y) * sc.render.resolution_y


def add_glow(img, radius, strength=0.55):
    """Soft mint bloom around emissive pixels (runes, lantern, eyes)."""
    r, g, b, a = img.split()
    # mint-ish pixels: strong green, green clearly above red
    mask = Image.merge("RGB", (r, g, b)).convert("RGB")
    px = mask.load()
    m = Image.new("L", img.size, 0)
    mp = m.load()
    ap = a.load()
    W, H = img.size
    for y in range(H):
        for x in range(W):
            R, G, B = px[x, y]
            if ap[x, y] > 128 and G > 190 and G - R > 40 and B > 120:
                mp[x, y] = 255
    if not m.getbbox():
        return img
    blur = m.filter(ImageFilter.GaussianBlur(radius))
    blur = blur.point(lambda v: min(255, int(v * 1.6)))
    glow = Image.new("RGBA", img.size, (109, 255, 180, 0))
    glow.putalpha(blur.point(lambda v: int(v * strength)))
    # glow sits behind the sprite where opaque, adds a halo where transparent
    under = Image.alpha_composite(glow, img)
    over = Image.alpha_composite(img, glow)
    # keep crisp rune strokes on top: blend, then lift with screen on glow area
    return Image.blend(under, over, 0.45)


def post(name, raw_path, muzzle_px):
    img = Image.open(raw_path).convert("RGBA")
    alpha = img.split()[3]
    bbox = alpha.point(lambda v: 255 if v > 10 else 0).getbbox()
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    s = (FINAL_LONG - 2 * PAD) / max(bw, bh) if bw >= bh else (FINAL_LONG - PAD) / bh
    if name in GLOW:
        img = add_glow(img, GLOW[name][0] / s, GLOW[name][1])
    crop = img.crop(bbox)
    tw, th = max(1, round(bw * s)), max(1, round(bh * s))
    crop = crop.resize((tw, th), Image.LANCZOS)
    W, H = tw + 2 * PAD, th + PAD
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.paste(crop, (PAD, PAD))
    mx = ((muzzle_px[0] - x0) * s + PAD) / W
    my = ((muzzle_px[1] - y0) * s + PAD) / H
    path = os.path.join(OUT_DIR, f"{name}.png")
    out.save(path, optimize=True)
    if os.path.getsize(path) > 250 * 1024:
        q = out.quantize(colors=255, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        q.save(path, optimize=True)
    return {"file": f"{name}.png", "w": W, "h": H,
            "muzzle": [round(mx, 4), round(my, 4)]}


GLOW = {"relictank": (9, 0.8), "horror": (7, 0.8)}


def render_one(name):
    t0 = time.time()
    Ctx.objects = []
    _MAT_CACHE.clear()
    sc = reset_scene()
    muzzle = MODELS[name]()
    cam = setup_camera(sc)
    mpx = project(sc, cam, muzzle)
    os.makedirs(TMP_DIR, exist_ok=True)
    raw = os.path.join(TMP_DIR, f"{name}_raw.png")
    sc.render.filepath = raw
    bpy.ops.render.render(write_still=True)
    info = post(name, raw, mpx)
    print(f"[sprites] {name}: {info['w']}x{info['h']} muzzle={info['muzzle']} "
          f"({time.time() - t0:.1f}s)", flush=True)
    return info


def main():
    names = [a for a in sys.argv[1:] if a in MODELS] or list(MODELS)
    os.makedirs(OUT_DIR, exist_ok=True)
    json_path = os.path.join(OUT_DIR, "sprites.json")
    meta = {}
    if os.path.exists(json_path):
        try:
            with open(json_path) as f:
                meta = json.load(f)
        except Exception:
            meta = {}
    t0 = time.time()
    for n in names:
        meta[n] = render_one(n)
    meta = {k: meta[k] for k in MODELS if k in meta}
    with open(json_path, "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    keep = os.environ.get("KEEP_RAW")
    if not keep and os.path.isdir(TMP_DIR):
        for fn in os.listdir(TMP_DIR):
            os.remove(os.path.join(TMP_DIR, fn))
        os.rmdir(TMP_DIR)
    print(f"[sprites] done in {time.time() - t0:.1f}s -> {OUT_DIR}")


if __name__ == "__main__":
    main()
