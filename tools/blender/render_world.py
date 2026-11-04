"""Pre-rendered 3D backdrops, the forward base and the war-table map boards.

Run (from the repo root):
    /tmp/claude-0/blendenv/bin/python tools/blender/render_world.py [target ...]

Targets: us_farm us_city eu_hedgerow eu_village asia_jungle asia_snow base
         na eu asia            (no arguments = everything)
Groups:  backdrops  maps

Same look as tools/blender/render_sprites.py: emission-only toon banding
with a key light from the upper left, inverted-hull outlines in #1b1a14,
Cycles CPU, Pillow post-processing.  Backdrops add distance haze in the
shader (outlines fade out with distance) and receive real hard sun
shadows on the ground only, so the props sit on the terrain.

Map boards are built from Natural Earth 1:50m data (land, lakes,
countries, rivers).  The GeoJSON is downloaded once into a cache folder
outside the repo (env SQUAD_GEO_CACHE, default /tmp/squad_ne_cache).

Outputs
    assets/bg/<name>.jpg   1600x900 backdrops + base.jpg, bg.json
    assets/maps/<id>.jpg   1600x1100 map boards, maps.json (city fx/fy)
Set KEEP_RAW=1 to keep the raw Cycles renders in the scratch folder.
"""
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

import bpy  # noqa: E402  (must precede bmesh/mathutils)
import bmesh
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector
from mathutils.geometry import tessellate_polygon
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BG_DIR = os.path.join(ROOT, "assets", "bg")
MAP_DIR = os.path.join(ROOT, "assets", "maps")
WORLD_JSON = os.path.join(ROOT, "data", "world.json")
GEO_CACHE = os.environ.get("SQUAD_GEO_CACHE",
                           os.path.join(tempfile.gettempdir(), "squad_ne_cache"))
TMP_DIR = os.environ.get("SQUAD_RENDER_TMP",
                         os.path.join(tempfile.gettempdir(), "squad_world_tmp"))
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"

OUTLINE_HEX = "#1b1a14"
MINT = "#6dffb4"
BANDS = [(-2.0, 0.58), (0.0, 0.80), (0.30, 1.0), (0.66, 1.16)]


# --------------------------------------------------------------------------
# colour helpers
# --------------------------------------------------------------------------
def srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def hexcol(h, a=1.0):
    return tuple(srgb_to_lin(v / 255.0) for v in hex_rgb(h)) + (a,)


def mix_hex(a, b, t):
    ra, rb = hex_rgb(a), hex_rgb(b)
    return "#%02x%02x%02x" % tuple(int(round(x + (y - x) * t)) for x, y in zip(ra, rb))


# --------------------------------------------------------------------------
# scene
# --------------------------------------------------------------------------
class Ctx:
    outline = 0.0        # world-unit hull thickness (0 = no outline)
    cam_pos = Vector((0, 0, 0))
    outline_k = 0.0      # backdrops: hull thickness per metre of distance
    outline_far = 0.0    # backdrops: no hull beyond this distance
    haze = None          # (hex, near, far, max) distance haze for toon mats
    key = Vector((-0.5, -0.62, 0.78)).normalized()
    bands = BANDS
    objects = []
    lights = []          # [(Vector pos, hex, radius, strength)] shader lights
    snowy = False
    push = None          # backdrops: (y, offset) move props beyond y back


def reset_scene(samples=16):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = False
    sc.cycles.use_denoising = False
    sc.cycles.max_bounces = 0
    sc.cycles.diffuse_bounces = 0
    sc.cycles.glossy_bounces = 0
    sc.cycles.transmission_bounces = 0
    sc.cycles.transparent_max_bounces = 24
    sc.cycles.use_light_tree = False
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
    Ctx.objects = []
    Ctx.lights = []
    _MAT_CACHE.clear()
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


def _new_mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    try:
        m.emission_sampling = "NONE"   # emissive props never act as lights
    except Exception:
        pass
    m.node_tree.nodes.clear()
    return m, m.node_tree


def _band_ramp(nt, normal_out, bands, key):
    dot = nt.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = key
    nt.links.new(normal_out, dot.inputs[0])
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = -1.0
    mr.inputs["From Max"].default_value = 1.0
    nt.links.new(dot.outputs["Value"], mr.inputs["Value"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    els = ramp.color_ramp.elements
    els[0].position = 0.0
    v = bands[0][1]
    els[0].color = (v, v, v, 1)
    els[1].position = (bands[1][0] + 1) / 2
    v = bands[1][1]
    els[1].color = (v, v, v, 1)
    for thr, val in bands[2:]:
        e = els.new((thr + 1) / 2)
        e.color = (val, val, val, 1)
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    return ramp.outputs["Color"]


def _mul(nt, a, b, blend="MULTIPLY", fac=1.0):
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = blend
    _sock(mix.inputs, "Factor_Float").default_value = fac
    for sock, val in ((_sock(mix.inputs, "A_Color"), a), (_sock(mix.inputs, "B_Color"), b)):
        if isinstance(val, tuple):
            sock.default_value = val
        else:
            nt.links.new(val, sock)
    return mix, _sock(mix.outputs, "Result_Color")


def _haze_fac(nt, near, far, mx, power=1.0):
    cd = nt.nodes.new("ShaderNodeCameraData")
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.clamp = True
    mr.inputs["From Min"].default_value = near
    mr.inputs["From Max"].default_value = far
    mr.inputs["To Min"].default_value = 0.0
    mr.inputs["To Max"].default_value = 1.0
    nt.links.new(cd.outputs["View Distance"], mr.inputs["Value"])
    pw = nt.nodes.new("ShaderNodeMath")
    pw.operation = "POWER"
    pw.inputs[1].default_value = power
    nt.links.new(mr.outputs["Result"], pw.inputs[0])
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[1].default_value = mx
    nt.links.new(pw.outputs[0], mul.inputs[0])
    return mul.outputs[0]


def _shader_lights(nt, colour_out, base_out):
    """Add warm point-light pools (lanterns) computed in the shader."""
    if not Ctx.lights:
        return colour_out
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    acc = colour_out
    for pos, hx, radius, strength in Ctx.lights:
        sub = nt.nodes.new("ShaderNodeVectorMath")
        sub.operation = "SUBTRACT"
        sub.inputs[0].default_value = pos
        nt.links.new(geo.outputs["Position"], sub.inputs[1])
        ln = nt.nodes.new("ShaderNodeVectorMath")
        ln.operation = "LENGTH"
        nt.links.new(sub.outputs[0], ln.inputs[0])
        nrm = nt.nodes.new("ShaderNodeVectorMath")
        nrm.operation = "NORMALIZE"
        nt.links.new(sub.outputs[0], nrm.inputs[0])
        dt = nt.nodes.new("ShaderNodeVectorMath")
        dt.operation = "DOT_PRODUCT"
        nt.links.new(nrm.outputs[0], dt.inputs[0])
        nt.links.new(geo.outputs["Normal"], dt.inputs[1])
        # facing term, banded: 0.35 back, 1.0 front
        fr = nt.nodes.new("ShaderNodeMapRange")
        fr.interpolation_type = "STEPPED"
        fr.inputs["From Min"].default_value = -0.2
        fr.inputs["From Max"].default_value = 1.0
        fr.inputs["To Min"].default_value = 0.35
        fr.inputs["To Max"].default_value = 1.0
        fr.inputs["Steps"].default_value = 2.0
        nt.links.new(dt.outputs["Value"], fr.inputs["Value"])
        # distance falloff, banded into 3 steps
        fo = nt.nodes.new("ShaderNodeMapRange")
        fo.interpolation_type = "STEPPED"
        fo.inputs["From Min"].default_value = radius
        fo.inputs["From Max"].default_value = 0.0
        fo.inputs["To Min"].default_value = 0.0
        fo.inputs["To Max"].default_value = 1.0
        fo.inputs["Steps"].default_value = 4.0
        nt.links.new(ln.outputs["Value"], fo.inputs["Value"])
        m1 = nt.nodes.new("ShaderNodeMath")
        m1.operation = "MULTIPLY"
        nt.links.new(fr.outputs["Result"], m1.inputs[0])
        nt.links.new(fo.outputs["Result"], m1.inputs[1])
        m2 = nt.nodes.new("ShaderNodeMath")
        m2.operation = "MULTIPLY"
        m2.inputs[1].default_value = strength
        nt.links.new(m1.outputs[0], m2.inputs[0])
        # light colour * base colour * amount, added
        _, tinted = _mul(nt, base_out, hexcol(hx))
        sc = nt.nodes.new("ShaderNodeVectorMath")
        sc.operation = "SCALE"
        nt.links.new(tinted, sc.inputs[0])
        nt.links.new(m2.outputs[0], sc.inputs["Scale"])
        add = nt.nodes.new("ShaderNodeVectorMath")
        add.operation = "ADD"
        nt.links.new(acc, add.inputs[0])
        nt.links.new(sc.outputs[0], add.inputs[1])
        acc = add.outputs[0]
    return acc


def toon(name, base, patches=None, patch_scale=1.3, emissive=False, bands=None,
         image=None, haze=True, strength=1.0, coords="Object"):
    """Emission-only toon material (see render_sprites.py).

    base: hex colour; patches: [(threshold, hex)] noise blobs; image: a
    bpy image sampled with the mesh UVs as base colour; emissive: flat
    unshaded (glow); haze: blend toward Ctx.haze by camera distance.
    """
    key = (name,)
    if key in _MAT_CACHE:
        return _MAT_CACHE[key]
    m, nt = _new_mat(name)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = strength
    nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
    if image is not None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.interpolation = "Linear"
        tex.extension = "EXTEND"
        uv = nt.nodes.new("ShaderNodeUVMap")
        nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
        base_out = tex.outputs["Color"]
    elif patches:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = patch_scale
        noise.inputs["Detail"].default_value = 0.0
        noise.inputs["Roughness"].default_value = 0.4
        nt.links.new(tc.outputs[coords], noise.inputs["Vector"])
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

    if emissive:
        col = base_out
    else:
        geo = nt.nodes.new("ShaderNodeNewGeometry")
        band = _band_ramp(nt, geo.outputs["Normal"], bands or Ctx.bands, Ctx.key)
        _, col = _mul(nt, base_out, band)
        col = _shader_lights(nt, col, base_out)
    if haze and Ctx.haze and not emissive:
        hx, near, far, mx = Ctx.haze[:4]
        fac = _haze_fac(nt, near, far, mx, Ctx.haze[4] if len(Ctx.haze) > 4 else 1.0)
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        nt.links.new(fac, _sock(mix.inputs, "Factor_Float"))
        nt.links.new(col, _sock(mix.inputs, "A_Color"))
        _sock(mix.inputs, "B_Color").default_value = hexcol(hx)
        col = _sock(mix.outputs, "Result_Color")
    nt.links.new(col, em.inputs["Color"])
    _MAT_CACHE[key] = m
    return m


def ground_mat(name, base, patches=None, patch_scale=0.05, shadow=0.62, image=None,
               sun_strength=None):
    """Ground that receives real hard sun shadows: emission (shadow level)
    + diffuse lit only by the sun lamp, then hazed by distance."""
    key = (name,)
    if key in _MAT_CACHE:
        return _MAT_CACHE[key]
    m, nt = _new_mat(name)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if image is not None:
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.extension = "EXTEND"
        uv = nt.nodes.new("ShaderNodeUVMap")
        nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
        base_out = tex.outputs["Color"]
    elif patches:
        tc = nt.nodes.new("ShaderNodeTexCoord")
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = patch_scale
        noise.inputs["Detail"].default_value = 1.0
        noise.inputs["Roughness"].default_value = 0.5
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
    # ambient (shadow) part, with shader lantern pools
    _, amb = _mul(nt, base_out, (shadow, shadow, shadow, 1))
    amb = _shader_lights(nt, amb, base_out)
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(amb, em.inputs["Color"])
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse")
    nt.links.new(base_out, dif.inputs["Color"])
    add = nt.nodes.new("ShaderNodeAddShader")
    nt.links.new(em.outputs[0], add.inputs[0])
    nt.links.new(dif.outputs[0], add.inputs[1])
    surf = add.outputs[0]
    if Ctx.haze:
        hx, near, far, mx = Ctx.haze[:4]
        fac = _haze_fac(nt, near, far, mx, Ctx.haze[4] if len(Ctx.haze) > 4 else 1.0)
        hz = nt.nodes.new("ShaderNodeEmission")
        hz.inputs["Color"].default_value = hexcol(hx)
        ms = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(fac, ms.inputs[0])
        nt.links.new(surf, ms.inputs[1])
        nt.links.new(hz.outputs[0], ms.inputs[2])
        surf = ms.outputs[0]
    nt.links.new(surf, out.inputs["Surface"])
    _MAT_CACHE[key] = m
    return m


def add_sun(direction, strength, angle=0.2):
    """Sun lamp shining along -direction (direction points toward the sun)."""
    ld = bpy.data.lights.new("Sun", "SUN")
    ld.energy = strength
    ld.angle = math.radians(angle)
    ob = bpy.data.objects.new("Sun", ld)
    bpy.context.scene.collection.objects.link(ob)
    d = Vector(direction).normalized()
    ob.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    return ob


def outline_mat():
    key = ("__outline",)
    if key in _MAT_CACHE:
        return _MAT_CACHE[key]
    m, nt = _new_mat("Outline")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    em = nt.nodes.new("ShaderNodeEmission")
    col = hexcol(OUTLINE_HEX)
    if Ctx.haze:
        hx, near, far, mx = Ctx.haze[:4]
        fac = _haze_fac(nt, near, far, mx, Ctx.haze[4] if len(Ctx.haze) > 4 else 1.0)
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        nt.links.new(fac, _sock(mix.inputs, "Factor_Float"))
        _sock(mix.inputs, "A_Color").default_value = col
        _sock(mix.inputs, "B_Color").default_value = hexcol(hx)
        nt.links.new(_sock(mix.outputs, "Result_Color"), em.inputs["Color"])
    else:
        em.inputs["Color"].default_value = col
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(geo.outputs["Backfacing"], mix.inputs[0])
    nt.links.new(em.outputs[0], mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    _MAT_CACHE[key] = m
    return m


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------
_MESH_CACHE = {}


def _hull_thickness(loc, outline):
    if not outline:
        return 0.0
    if Ctx.outline_k > 0:
        d = (Vector(loc) - Ctx.cam_pos).length
        if Ctx.outline_far and d > Ctx.outline_far:
            return 0.0
        return Ctx.outline_k * d * outline
    return Ctx.outline * outline


def _finish(bm, name, mat, loc=(0, 0, 0), rot=(0, 0, 0), smooth=False,
            bevel=0.0, seg=1, outline=1.0, sharp_angle=40.0, scale=None):
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
    me.materials.append(mat)
    return place(me, name, loc, rot, bevel=bevel, seg=seg, outline=outline, scale=scale)


def place(me, name, loc=(0, 0, 0), rot=(0, 0, 0), bevel=0.0, seg=1, outline=1.0,
          scale=None):
    """Link an object using mesh `me` (shared data ok) with optional hull."""
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    ob.rotation_euler = [math.radians(a) for a in rot]
    if scale is not None:
        ob.scale = scale if hasattr(scale, "__len__") else (scale, scale, scale)
    if bevel > 0:
        b = ob.modifiers.new("bevel", "BEVEL")
        b.width = bevel
        b.segments = seg
        b.limit_method = "ANGLE"
        b.angle_limit = math.radians(35)
    th = _hull_thickness(loc, outline)
    if th > 0:
        if outline_mat().name not in [m.name for m in me.materials if m]:
            me.materials.append(outline_mat())
        s = ob.modifiers.new("outline", "SOLIDIFY")
        sc = ob.scale[0] if scale is not None else 1.0
        s.thickness = th / max(sc, 1e-4)
        s.offset = 1.0
        s.use_flip_normals = True
        s.use_even_offset = False
        s.use_rim = False
        s.material_offset = len(me.materials) - 1
    Ctx.objects.append(ob)
    return ob


def box(name, size, loc, mat, rot=(0, 0, 0), bevel=0.0, outline=1.0):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)
    return _finish(bm, name, mat, loc, rot, bevel=bevel, outline=outline)


def cyl(name, r, depth, loc, mat, r2=None, verts=12, rot=(0, 0, 0), outline=1.0,
        smooth=True, caps=True):
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=caps, cap_tris=False, segments=verts,
                          radius1=r, radius2=r if r2 is None else r2, depth=depth)
    return _finish(bm, name, mat, loc, rot, smooth=smooth, outline=outline)


def sphere(name, r, loc, mat, scale=(1, 1, 1), rot=(0, 0, 0), segs=12, rings=7,
           outline=1.0, smooth=False):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=r)
    bmesh.ops.scale(bm, vec=Vector(scale), verts=bm.verts)
    return _finish(bm, name, mat, loc, rot, smooth=smooth, outline=outline,
                   sharp_angle=80)


def ico(name, r, loc, mat, scale=(1, 1, 1), rot=(0, 0, 0), sub=1, outline=1.0,
        jitter=0.0, seed=0):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=r)
    if jitter:
        rnd = random.Random(seed)
        for v in bm.verts:
            v.co *= 1 + rnd.uniform(-jitter, jitter)
    bmesh.ops.scale(bm, vec=Vector(scale), verts=bm.verts)
    return _finish(bm, name, mat, loc, rot, outline=outline)


def prism(name, pts, y0, y1, mat, outline=1.0, loc=(0, 0, 0), rot=(0, 0, 0), bevel=0.0):
    """Extrude an XZ profile (list of (x, z)) from y0 to y1."""
    bm = bmesh.new()
    front = [bm.verts.new((x, y0, z)) for x, z in pts]
    back = [bm.verts.new((x, y1, z)) for x, z in pts]
    bm.faces.new(front)
    bm.faces.new(list(reversed(back)))
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((front[i], front[j], back[j], back[i]))
    return _finish(bm, name, mat, loc, rot, outline=outline, bevel=bevel)


def bar(name, p0, p1, w, mat, outline=1.0, d=None):
    """Square beam between two 3D points."""
    p0, p1 = Vector(p0), Vector(p1)
    v = p1 - p0
    L = v.length
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector((w, d or w, L)), verts=bm.verts)
    q = v.normalized().to_track_quat("Z", "Y")
    ob = _finish(bm, name, mat, (p0 + p1) / 2, outline=outline)
    ob.rotation_euler = q.to_euler()
    return ob


def curve_tube(name, pts, radius, mat, res=3):
    cd = bpy.data.curves.new(name, "CURVE")
    cd.dimensions = "3D"
    cd.bevel_depth = radius
    cd.bevel_resolution = 0
    cd.fill_mode = "FULL"
    sp = cd.splines.new("POLY")
    sp.points.add(len(pts) - 1)
    for p, q in zip(sp.points, pts):
        p.co = (q[0], q[1], q[2], 1)
    ob = bpy.data.objects.new(name, cd)
    cd.materials.append(mat)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def multi_tube(name, polylines, radius, mat):
    cd = bpy.data.curves.new(name, "CURVE")
    cd.dimensions = "3D"
    cd.bevel_depth = radius
    cd.bevel_resolution = 0
    cd.fill_mode = "FULL"
    for pts in polylines:
        if len(pts) < 2:
            continue
        sp = cd.splines.new("POLY")
        sp.points.add(len(pts) - 1)
        for p, q in zip(sp.points, pts):
            p.co = (q[0], q[1], q[2], 1)
    ob = bpy.data.objects.new(name, cd)
    cd.materials.append(mat)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def render_raw(sc, name):
    os.makedirs(TMP_DIR, exist_ok=True)
    raw = os.path.join(TMP_DIR, f"{name}_raw.png")
    sc.render.filepath = raw
    bpy.ops.render.render(write_still=True)
    return raw


def save_jpeg(img, path, quality, max_kb):
    q = quality
    while True:
        img.convert("RGB").save(path, "JPEG", quality=q, optimize=True,
                                progressive=True, subsampling=0 if q >= 88 else 2)
        if os.path.getsize(path) <= max_kb * 1024 or q <= 60:
            break
        q -= 3
    return os.path.getsize(path)


# ==========================================================================
# WORLD MAP BOARDS
# ==========================================================================
MAP_W, MAP_H = 1600, 1100
TEX_W = 3400                 # texture px across the whole board
FRAME_W = 40.0               # world units across the frame


MAPS = {
    "na": dict(tilt=20.0, grid=5, margin=(0.085, 0.13), lake_min=0.08,
               river_rank=6, snowline=0.92, relief=0.8),
    "eu": dict(tilt=20.0, grid=1, margin=(0.085, 0.13), lake_min=0.004,
               river_rank=6, snowline=0.85, relief=0.55),
    "asia": dict(tilt=20.0, grid=5, margin=(0.10, 0.10), lake_min=0.05,
                 river_rank=6, snowline=0.98, relief=0.8),
}

# palette
LAND_RAMP = ["#c2b685", "#ada574", "#999a63", "#878d56", "#777f4c", "#6a7445"]
ARID_RAMP = ["#cbb98a", "#bdab7b", "#b09f70", "#a29468", "#978b60", "#8b825a"]
SNOW_COL = "#dfe1d4"
WATER = ["#3e7471", "#336664", "#2a5859", "#234b4d", "#1e4244"]
WALL_HEX = "#6e6444"
BORDER_HEX = "#3f3d2a"


def geo_path(name):
    os.makedirs(GEO_CACHE, exist_ok=True)
    p = os.path.join(GEO_CACHE, name + ".geojson")
    if not os.path.exists(p) or os.path.getsize(p) < 1000:
        url = NE_URL + name + ".geojson"
        print(f"[maps] downloading {url}", flush=True)
        tmp = p + ".part"
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
        except Exception as e:  # proxy / CA issues: fall back to curl
            print(f"[maps] urllib failed ({e}); trying curl", flush=True)
            subprocess.check_call(["curl", "-sSfL", "-o", tmp, url])
        os.replace(tmp, p)
    return p


def load_geo(name):
    with open(geo_path(name)) as f:
        return json.load(f)


def iter_polys(geom):
    if geom is None:
        return
    if geom["type"] == "Polygon":
        yield geom["coordinates"]
    elif geom["type"] == "MultiPolygon":
        for p in geom["coordinates"]:
            yield p


def iter_lines(geom):
    if geom is None:
        return
    if geom["type"] == "LineString":
        yield geom["coordinates"]
    elif geom["type"] == "MultiLineString":
        for p in geom["coordinates"]:
            yield p


def ring_bbox(r):
    xs = [p[0] for p in r]
    ys = [p[1] for p in r]
    return min(xs), min(ys), max(xs), max(ys)


def clip_ring(ring, box):
    """Sutherland-Hodgman clip of a closed ring to an axis-aligned box."""
    x0, y0, x1, y1 = box
    pts = [tuple(p[:2]) for p in ring]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]

    def clip(pts, inside, inter):
        out = []
        n = len(pts)
        for i in range(n):
            a, b = pts[i - 1], pts[i]
            ia, ib = inside(a), inside(b)
            if ib:
                if not ia:
                    out.append(inter(a, b))
                out.append(b)
            elif ia:
                out.append(inter(a, b))
        return out

    def ix(xc):
        return lambda a, b: (xc, a[1] + (b[1] - a[1]) * (xc - a[0]) / (b[0] - a[0]))

    def iy(yc):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (yc - a[1]) / (b[1] - a[1]), yc)

    for inside, inter in ((lambda p: p[0] >= x0, ix(x0)), (lambda p: p[0] <= x1, ix(x1)),
                          (lambda p: p[1] >= y0, iy(y0)), (lambda p: p[1] <= y1, iy(y1))):
        if not pts:
            break
        pts = clip(pts, inside, inter)
    # drop consecutive duplicates
    clean = []
    for p in pts:
        if not clean or abs(p[0] - clean[-1][0]) > 1e-9 or abs(p[1] - clean[-1][1]) > 1e-9:
            clean.append(p)
    if len(clean) > 1 and clean[0] == clean[-1]:
        clean.pop()
    return clean


def signed_area(r):
    a = 0.0
    for i in range(len(r)):
        x0, y0 = r[i - 1]
        x1, y1 = r[i]
        a += x0 * y1 - x1 * y0
    return a / 2


def point_in_ring(p, r):
    x, y = p
    inside = False
    n = len(r)
    for i in range(n):
        x0, y0 = r[i - 1]
        x1, y1 = r[i]
        if (y0 > y) != (y1 > y):
            if x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                inside = not inside
    return inside


def vnoise(h, w, cells, seed, octaves=4):
    """fbm value noise in 0..1, shape (h, w)."""
    rng = np.random.default_rng(seed)
    acc = np.zeros((h, w), np.float32)
    amp, tot = 1.0, 0.0
    c = cells
    for _ in range(octaves):
        cw = max(2, int(c))
        ch = max(2, int(c * h / w))
        small = (rng.random((ch, cw)) * 255).astype(np.uint8)
        big = Image.fromarray(small).resize((w, h), Image.BICUBIC)
        acc += amp * np.asarray(big, np.float32) / 255.0
        tot += amp
        amp *= 0.5
        c *= 2.1
    return acc / tot


def blur_arr(a, r):
    im = Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.GaussianBlur(r)), np.float32) / 255.0


def ramp_lookup(ramp_hex, t):
    cols = np.array([hex_rgb(h) for h in ramp_hex], np.float32)
    n = len(cols)
    idx = np.clip(t * n, 0, n - 1e-3)
    i = np.floor(idx).astype(np.int32)
    return cols[i]


# relief ridgelines: ([(lon, lat), ...], half-width deg, height)
RANGES = {
    "na": [
        ([(-106.5, 31.5), (-105.6, 35.5), (-105.7, 38.5), (-106.0, 40.5), (-107.5, 42.5),
          (-110.0, 44.5), (-112.5, 47.5), (-114.5, 49.5)], 1.6, 1.0),
        ([(-111.5, 36.5), (-111.6, 41.5)], 1.0, 0.7),
        ([(-108.5, 37.0), (-107.5, 39.0)], 0.9, 0.85),
        ([(-86.6, 33.6), (-84.5, 35.2), (-82.6, 36.2), (-80.6, 37.4), (-79.2, 38.8),
          (-77.8, 40.3), (-76.3, 41.3), (-74.8, 42.2)], 0.75, 0.55),
        ([(-74.7, 43.5), (-74.0, 44.4)], 0.45, 0.45),
        ([(-73.0, 42.6), (-72.0, 43.6), (-71.2, 44.4), (-69.8, 45.6)], 0.6, 0.4),
        ([(-94.2, 35.9), (-92.5, 36.8), (-91.2, 37.4)], 0.7, 0.28),
        ([(-95.3, 34.6), (-93.0, 34.6)], 0.4, 0.25),
        ([(-103.7, 43.5), (-103.6, 44.4)], 0.35, 0.32),
        ([(-80.0, 47.0), (-75.0, 47.4), (-70.5, 48.2), (-67.0, 49.0)], 1.2, 0.3),
        ([(-100.6, 22.0), (-100.0, 25.3), (-101.5, 27.5)], 1.0, 0.6),
        ([(-104.5, 24.0), (-105.8, 27.5), (-107.5, 30.5)], 1.4, 0.75),
    ],
    "eu": [
        ([(5.8, 44.4), (6.8, 45.4), (7.5, 45.95), (8.5, 46.4), (10.0, 46.6),
          (11.5, 46.95), (13.0, 47.15)], 0.6, 1.0),
        ([(5.6, 46.2), (6.4, 46.9), (7.5, 47.45)], 0.25, 0.42),
        ([(6.9, 47.85), (7.15, 48.4), (7.45, 49.0)], 0.22, 0.45),
        ([(8.0, 47.7), (8.25, 48.3), (8.45, 48.85)], 0.22, 0.45),
        ([(8.7, 48.05), (9.5, 48.45), (10.4, 48.75)], 0.22, 0.3),
        ([(4.6, 49.85), (5.6, 50.1), (6.4, 50.3), (7.0, 50.3)], 0.3, 0.35),
        ([(6.8, 49.75), (7.8, 50.0), (8.5, 50.25)], 0.22, 0.3),
        ([(7.5, 51.1), (8.6, 51.2)], 0.22, 0.28),
        ([(9.5, 50.5), (10.0, 50.4)], 0.2, 0.28),
        ([(2.2, 45.0), (2.9, 45.5), (3.7, 45.8), (4.4, 45.3)], 0.5, 0.6),
        ([(3.9, 47.0), (4.2, 47.45)], 0.2, 0.25),
        ([(-4.0, 48.3), (-2.6, 48.4), (-1.0, 48.55), (0.0, 48.4)], 0.25, 0.1),
        ([(10.4, 51.75), (11.0, 51.7)], 0.18, 0.3),
        ([(10.2, 50.6), (11.5, 50.5)], 0.2, 0.3),
        ([(12.0, 50.35), (13.5, 50.5)], 0.22, 0.35),
        ([(12.5, 49.2), (13.6, 48.8)], 0.25, 0.35),
        ([(-1.5, 43.0), (1.0, 42.7), (3.0, 42.5)], 0.35, 0.9),
    ],
    "asia": [
        ([(96.5, 25.0), (98.8, 27.0), (100.4, 29.0), (101.8, 31.0), (102.8, 33.0),
          (102.0, 35.0), (100.0, 37.0)], 1.6, 1.0),
        ([(104.0, 33.8), (107.0, 33.8), (110.0, 33.7), (112.0, 33.5)], 0.45, 0.65),
        ([(106.0, 32.0), (109.0, 31.8), (110.5, 31.4)], 0.35, 0.5),
        ([(113.5, 35.0), (113.8, 36.5), (114.0, 38.0), (114.8, 39.6), (115.8, 40.4)],
         0.35, 0.55),
        ([(111.0, 35.8), (111.5, 38.5)], 0.3, 0.42),
        ([(108.0, 41.0), (111.0, 41.25), (114.0, 41.6)], 0.35, 0.45),
        ([(115.6, 40.6), (118.0, 40.5), (119.5, 40.3)], 0.3, 0.4),
        ([(117.5, 42.5), (119.5, 44.5), (121.0, 47.0), (122.5, 49.5)], 0.6, 0.55),
        ([(124.5, 40.6), (127.0, 41.8), (128.5, 42.3), (129.6, 43.6), (131.0, 45.0)],
         0.55, 0.55),
        ([(127.0, 47.5), (129.5, 49.0)], 0.45, 0.4),
        ([(127.5, 40.4), (128.6, 38.5), (129.1, 37.0), (128.7, 35.4)], 0.32, 0.55),
        ([(126.0, 40.6), (128.0, 41.2), (129.5, 41.9)], 0.4, 0.55),
        ([(109.5, 25.4), (112.0, 25.2), (114.5, 24.9), (116.0, 24.9)], 0.4, 0.45),
        ([(116.3, 26.3), (117.5, 27.5), (118.5, 28.3)], 0.35, 0.5),
        ([(109.0, 28.5), (110.4, 27.2), (110.8, 29.8)], 0.35, 0.4),
        ([(114.0, 31.2), (116.5, 31.0)], 0.25, 0.35),
        ([(117.0, 36.3), (118.5, 36.0)], 0.25, 0.32),
        ([(120.8, 22.4), (121.3, 24.4)], 0.25, 0.75),
        ([(130.8, 32.0), (131.0, 33.4)], 0.25, 0.5),
        ([(132.0, 34.6), (134.0, 35.0), (136.0, 35.6), (137.5, 36.2), (138.5, 36.7)],
         0.35, 0.75),
        ([(105.0, 21.8), (104.0, 20.0), (105.5, 18.0)], 0.35, 0.55),
        ([(102.8, 22.6), (104.6, 22.6)], 0.45, 0.55),
        ([(106.0, 36.0), (109.0, 37.0), (111.0, 36.2)], 1.0, 0.3),
        # Tibetan plateau, Yunnan-Guizhou plateau, Mongolian plateau (broad)
        ([(93.0, 30.0), (96.5, 32.5), (96.0, 36.0)], 3.2, 0.8),
        ([(101.5, 25.6), (104.0, 26.3), (106.5, 26.8)], 1.3, 0.42),
        ([(100.0, 45.5), (108.0, 44.0), (113.0, 44.2)], 2.6, 0.3),
    ],
}
PLATEAUS = {
    "na": [
        lambda lo, la: 0.34 * np.clip((-97.0 - lo) / 8.0, 0, 1),
    ],
}


class MapBuilder:
    def __init__(self, rid):
        self.rid = rid
        self.cfg = MAPS[rid]
        with open(WORLD_JSON) as f:
            world = json.load(f)
        self.cities = [(c["id"], c["lat"], c["lon"]) for c in world[rid]["cities"]]
        lats = [c[1] for c in self.cities]
        lons = [c[2] for c in self.cities]
        self.lat_c = (min(lats) + max(lats)) / 2
        self.lon_c = (min(lons) + max(lons)) / 2
        self.k = math.cos(math.radians(self.lat_c))
        self.tilt = math.radians(self.cfg["tilt"])
        self.aspect = MAP_W / MAP_H
        self.fit()

    # projection: degrees -> world units
    def proj(self, lon, lat):
        return ((lon - self.lon_c) * self.k * self.S, (lat - self.lat_c) * self.S)

    def unproj(self, x, y):
        return (x / (self.k * self.S) + self.lon_c, y / self.S + self.lat_c)

    def fit(self):
        mx, my = self.cfg["margin"]
        ct = math.cos(self.tilt)
        us = [(c[2] - self.lon_c) * self.k for c in self.cities]
        vs = [(c[1] - self.lat_c) * ct for c in self.cities]
        du, dv = max(us) - min(us), max(vs) - min(vs)
        W = max(du / (1 - 2 * mx), dv * self.aspect / (1 - 2 * my))
        self.S = FRAME_W / W
        self.cx = (max(us) + min(us)) / 2 * self.S
        self.cy = (max(vs) + min(vs)) / 2 / ct * self.S
        self.h = 0.34                                    # land height
        Hf = FRAME_W / self.aspect
        bw = FRAME_W * 0.62
        bh = Hf / ct * 0.64
        self.board = (self.cx - bw, self.cy - bh, self.cx + bw, self.cy + bh)
        lo0, la0 = self.unproj(self.board[0], self.board[1])
        lo1, la1 = self.unproj(self.board[2], self.board[3])
        self.geo_box = (lo0 - 0.5, la0 - 0.5, lo1 + 0.5, la1 + 0.5)
        print(f"[maps] {self.rid}: S={self.S:.3f} u/deg, lon {lo0:.1f}..{lo1:.1f} "
              f"lat {la0:.1f}..{la1:.1f}", flush=True)

    # ------------------------------------------------------------------ data
    def load(self):
        gb = self.geo_box
        lake_min = self.cfg["lake_min"]

        def overlaps(bb):
            return not (bb[2] < gb[0] or bb[0] > gb[2] or bb[3] < gb[1] or bb[1] > gb[3])

        self.land = []        # [(outer, [holes])] in world coords
        for f in load_geo("ne_50m_land")["features"]:
            for poly in iter_polys(f["geometry"]):
                if not overlaps(ring_bbox(poly[0])):
                    continue
                outer = clip_ring(poly[0], gb)
                if len(outer) < 3:
                    continue
                holes = [clip_ring(h, gb) for h in poly[1:]]
                self.land.append(([self.proj(*p) for p in outer],
                                  [[self.proj(*p) for p in h] for h in holes if len(h) >= 3]))
        lakes = []
        for f in load_geo("ne_50m_lakes")["features"]:
            for poly in iter_polys(f["geometry"]):
                bb = ring_bbox(poly[0])
                if not overlaps(bb):
                    continue
                if abs(signed_area([tuple(p[:2]) for p in poly[0]])) < lake_min:
                    continue
                r = clip_ring(poly[0], gb)
                if len(r) >= 3:
                    lakes.append([self.proj(*p) for p in r])
        self.lakes = lakes
        for lk in lakes:
            for i, (outer, holes) in enumerate(self.land):
                if point_in_ring(lk[0], outer):
                    holes.append(lk)
                    break
        # countries: shared edges = land borders; also per-country polygons
        feats = load_geo("ne_50m_admin_0_countries")["features"]
        edge_owner = {}
        self.countries = []
        for ci, f in enumerate(feats):
            name = f["properties"].get("ADMIN") or str(ci)
            for poly in iter_polys(f["geometry"]):
                if not overlaps(ring_bbox(poly[0])):
                    continue
                r = clip_ring(poly[0], gb)
                if len(r) >= 3:
                    self.countries.append((name, [self.proj(*p) for p in r]))
                for ring in poly:
                    for a, b in zip(ring[:-1], ring[1:]):
                        ka = (round(a[0], 5), round(a[1], 5))
                        kb = (round(b[0], 5), round(b[1], 5))
                        if ka == kb:
                            continue
                        e = (ka, kb) if ka < kb else (kb, ka)
                        edge_owner.setdefault(e, set()).add(ci)
        segs = [e for e, o in edge_owner.items() if len(o) >= 2
                and gb[0] <= e[0][0] <= gb[2] and gb[1] <= e[0][1] <= gb[3]]
        self.borders = [[self.proj(*p) for p in line] for line in chain_edges(segs)]
        self.rivers = []
        for f in load_geo("ne_50m_rivers_lake_centerlines")["features"]:
            rank = f["properties"].get("scalerank", 9) or 9
            if rank > self.cfg["river_rank"]:
                continue
            for line in iter_lines(f["geometry"]):
                if not overlaps(ring_bbox(line)):
                    continue
                self.rivers.append((rank, [self.proj(*p[:2]) for p in line]))
        print(f"[maps] {self.rid}: {len(self.land)} land polys, {len(lakes)} lakes, "
              f"{len(self.borders)} border lines, {len(self.rivers)} rivers", flush=True)

    # --------------------------------------------------------------- texture
    def to_px(self, pts):
        x0, y0, x1, y1 = self.board
        sx = self.TW / (x1 - x0)
        return [((x - x0) * sx, (y1 - y) * sx) for x, y in pts]

    def paint(self):
        x0, y0, x1, y1 = self.board
        TW = self.TW = TEX_W
        TH = self.TH = int(round(TEX_W * (y1 - y0) / (x1 - x0)))
        ppu = TW / (x1 - x0)                 # texture px per world unit
        self.ppu = ppu
        mask_im = Image.new("L", (TW, TH), 0)
        d = ImageDraw.Draw(mask_im)
        for outer, holes in self.land:
            d.polygon(self.to_px(outer), fill=255)
            for h in holes:
                d.polygon(self.to_px(h), fill=0)
        mask = np.asarray(mask_im, np.float32) / 255.0
        self.mask = mask
        rng_seed = {"na": 11, "eu": 23, "asia": 37}[self.rid]

        # geographic coordinate of every pixel (for tints and grid)
        xs = x0 + (np.arange(TW) + 0.5) / ppu
        ys = y1 - (np.arange(TH) + 0.5) / ppu
        lon = xs / (self.k * self.S) + self.lon_c
        lat = ys / self.S + self.lat_c
        LON, LAT = np.meshgrid(lon, lat)

        # ---- relief: synthetic heightfield (ranges + noise), low-res first
        u = ppu   # 1 world unit in px (frame is 40 units)
        n1 = vnoise(TH, TW, 7, rng_seed)
        n2 = vnoise(TH, TW, 26, rng_seed + 1, octaves=3)
        H = self.heightfield(LON, LAT, rng_seed)
        inland = 0.6 * blur_arr(mask, 0.8 * u) + 0.4 * blur_arr(mask, 3.0 * u)
        coast = np.clip((inland - 0.45) * 2.2, 0, 1)
        Hl = H * np.clip(coast * 6, 0, 1)            # relief fades at the shore
        Hl = Hl + 0.05 * coast + 0.06 * (n2 - 0.5) * coast
        # hillshade, toon-stepped (key light from the upper left)
        ppd = u * self.S                              # px per degree
        gy, gx = np.gradient(Hl * ppd)
        z = self.cfg.get("relief", 0.9)
        nx, ny, nz = -gx * z, -gy * z, np.ones_like(gx)
        nl = np.sqrt(nx * nx + ny * ny + nz * nz)
        L = np.array((-0.62, -0.55, 0.56))
        L = L / np.linalg.norm(L)
        shade = (nx * L[0] + ny * L[1] + nz * L[2]) / nl / L[2]
        shade = np.clip(shade, 0.35, 1.6)
        shade = np.round(shade * 7) / 7
        shade = blur_arr(shade / 2, 0.9) * 2
        shade = 1 + (shade - 1) * 0.55
        # colour terraces from coast distance + height + noise
        f = coast * 0.45 + n1 * 0.32 + np.clip(Hl, 0, 1) * 0.28 - 0.02
        f = np.clip(f + (n2 - 0.5) * 0.08, 0, 0.999)
        land = ramp_lookup(LAND_RAMP, f)
        arid = ramp_lookup(ARID_RAMP, f)
        # regional climate tints (diagonal gradients broken up by noise)
        if self.rid == "na":
            a = np.clip((-97.5 - LON) / 5.0 + (n1 - 0.5) * 1.2, 0, 1)
        elif self.rid == "asia":
            a = np.clip(((LAT - 35.0) / 6 + (108.0 - LON) / 9) * 0.7 + (n1 - 0.5) * 1.0, 0, 1)
        else:
            a = np.zeros_like(LON)
        a = (np.round(a * 3) / 3)[..., None]
        land = land * (1 - a * 0.8) + arid * a * 0.8
        # rock on the high ground, snow caps on the highest
        rock = np.clip((Hl - 0.42) / 0.3 + (n2 - 0.5) * 0.6, 0, 1)
        rock = (np.round(rock * 3) / 3)[..., None]
        land = land * (1 - rock * 0.6) + np.array(hex_rgb("#8c8466"), np.float32) * rock * 0.6
        snow_c = np.array(hex_rgb(SNOW_COL), np.float32)
        cap = np.clip((Hl - self.cfg.get("snowline", 0.8)) / 0.12 + (n2 - 0.5) * 0.8, 0, 1)
        cap = (np.round(cap * 2) / 2)[..., None]
        land = land * (1 - cap * 0.8) + snow_c * cap * 0.8
        if self.rid == "asia":
            s = np.clip((LAT - 44.0) / 5.0 + (n2 - 0.5) * 0.9 + (n1 - 0.5) * 0.6, 0, 1)
            s = (np.round(s * 3) / 3)[..., None]
            land = land * (1 - s * 0.6) + snow_c * s * 0.6
        land = land * shade[..., None]
        # subtle per-country tone
        tone_im = Image.new("L", (TW, TH), 128)
        dt = ImageDraw.Draw(tone_im)
        for name, ring in self.countries:
            hsh = sum(ord(ch) * (i + 7) for i, ch in enumerate(name)) % 5
            dt.polygon(self.to_px(ring), fill=128 + (hsh - 2) * 4)
        tone = np.asarray(tone_im, np.float32)[..., None] / 128.0
        land = land * tone
        # fine grain
        land = land * (0.97 + 0.06 * n2[..., None])

        # ---- water: depth bands from distance to land
        wcol = np.array([hex_rgb(h) for h in WATER], np.float32)
        depth = np.zeros((TH, TW), np.int32) + 4
        for i, r in enumerate((0.25, 0.65, 1.3, 2.4)[::-1]):
            near = blur_arr(mask, r * u) > 0.035
            depth[near] = 3 - i
        water = wcol[depth]
        water = water * (0.975 + 0.05 * vnoise(TH, TW, 40, rng_seed + 5, 2)[..., None])
        # drop shadow of the land toward the lower right (key light upper left)
        sh = Image.fromarray((mask * 255).astype(np.uint8))
        sh = ImageChops.offset(sh, int(0.16 * u), int(0.2 * u))
        sh = np.asarray(sh.filter(ImageFilter.GaussianBlur(0.08 * u)), np.float32) / 255
        water = water * (1 - 0.32 * sh[..., None])
        # dark coastline rim just outside the land
        rim = np.clip(blur_arr(mask, 0.06 * u) * 3.0, 0, 1) * (1 - mask)
        oc = np.array(hex_rgb(OUTLINE_HEX), np.float32)
        water = water * (1 - rim[..., None] * 0.75) + oc * rim[..., None] * 0.75

        img = land * mask[..., None] + water * (1 - mask[..., None])

        # ---- lat/long grid (faint)
        g = self.cfg["grid"]
        grid_im = Image.new("L", (TW, TH), 0)
        dg = ImageDraw.Draw(grid_im)
        gb = self.geo_box
        lw = max(2, int(0.045 * u))
        for lo in np.arange(math.ceil(gb[0] / g) * g, gb[2], g):
            (px, _), = self.to_px([self.proj(lo, self.lat_c)])
            dg.line([(px, 0), (px, TH)], fill=255, width=lw)
        for la in np.arange(math.ceil(gb[1] / g) * g, gb[3], g):
            (_, py), = self.to_px([self.proj(self.lon_c, la)])
            dg.line([(0, py), (TW, py)], fill=255, width=lw)
        grid = np.asarray(grid_im.filter(ImageFilter.GaussianBlur(0.6)), np.float32)[..., None] / 255
        light = np.array((215, 222, 196), np.float32)
        gmix = grid * (0.16 * (1 - mask[..., None]) + 0.10 * mask[..., None])
        img = img * (1 - gmix) + light * gmix

        # ---- rivers & painted border lines
        riv = Image.new("L", (TW, TH), 0)
        dr = ImageDraw.Draw(riv)
        for rank, line in self.rivers:
            w = max(2, int(u * (0.11 if rank <= 2 else 0.085 if rank <= 4 else 0.065)))
            dr.line(self.to_px(line), fill=255, width=w, joint="curve")
        rv = np.asarray(riv.filter(ImageFilter.GaussianBlur(0.7)), np.float32)[..., None] / 255
        rv = rv * mask[..., None]
        img = img * (1 - rv) + np.array(hex_rgb(WATER[1]), np.float32) * rv
        bl = Image.new("L", (TW, TH), 0)
        db = ImageDraw.Draw(bl)
        for line in self.borders:
            db.line(self.to_px(line), fill=255, width=max(2, int(0.16 * u)), joint="curve")
        bv = np.asarray(bl.filter(ImageFilter.GaussianBlur(0.12 * u)), np.float32)[..., None] / 255
        img = img * (1 - 0.22 * bv * mask[..., None])

        tex = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
        os.makedirs(TMP_DIR, exist_ok=True)
        p = os.path.join(TMP_DIR, f"map_{self.rid}_tex.png")
        tex.save(p)
        im = bpy.data.images.load(p)
        im.colorspace_settings.name = "sRGB"
        self.image = im

    def heightfield(self, LON, LAT, seed):
        """Relief in 0..~1 from hand-placed range ridgelines (lon/lat),
        domain-warped and broken up with ridged noise; computed at quarter
        resolution in float and upsampled."""
        TH, TW = LON.shape
        q = 4
        lo = LON[::q, ::q]
        la = LAT[::q, ::q]
        h, w = lo.shape
        H = np.zeros((h, w), np.float32)
        k = self.k
        span = (self.geo_box[3] - self.geo_box[1])
        wa = vnoise(h, w, 9, seed + 21, octaves=3) - 0.5
        wb = vnoise(h, w, 9, seed + 22, octaves=3) - 0.5
        for pts, width, height in RANGES[self.rid]:
            width = max(width, 0.022 * span)
            warp = width * 1.3
            lw = lo + wa * warp * 2
            law = la + wb * warp * 2
            d = np.full((h, w), 1e9, np.float32)
            for (ax, ay), (bx, by) in zip(pts[:-1], pts[1:]):
                px, py = (lw - ax) * k, law - ay
                vx, vy = (bx - ax) * k, by - ay
                t = np.clip((px * vx + py * vy) / (vx * vx + vy * vy + 1e-9), 0, 1)
                dd = (px - t * vx) ** 2 + (py - t * vy) ** 2
                d = np.minimum(d, dd)
            H = np.maximum(H, height * np.exp(-d / (width * width * 0.5)))
        cells = 55.0 * (w / 850)
        n = vnoise(h, w, cells, seed + 9, octaves=4)
        ridged = (1 - np.abs(2 * n - 1)) ** 2
        n3 = vnoise(h, w, cells * 2.3, seed + 10, octaves=3)
        r2 = (1 - np.abs(2 * n3 - 1)) ** 2
        H = H * (0.25 + 0.65 * ridged + 0.35 * r2)
        for fn in PLATEAUS.get(self.rid, []):
            H = np.maximum(H, fn(lo, la).astype(np.float32) * (0.9 + 0.2 * n))
        big = Image.fromarray(H.astype(np.float32), "F").resize((TW, TH), Image.BICUBIC)
        H = np.asarray(big, np.float32)
        fine = vnoise(TH, TW, cells * 3, seed + 3, octaves=3)
        return H * (0.85 + 0.3 * fine)

    # ------------------------------------------------------------------ mesh
    def uv_of(self, x, y):
        x0, y0, x1, y1 = self.board
        return ((x - x0) / (x1 - x0), (y - y0) / (y1 - y0))

    def build(self):
        h = self.h
        x0, y0, x1, y1 = self.board
        top = toon("map_top", "#888888", image=self.image, bands=self.map_bands, haze=False)
        wall = toon("map_wall", WALL_HEX, bands=self.map_bands, haze=False)
        # water board
        bm = bmesh.new()
        uvl = bm.loops.layers.uv.new("UVMap")
        vs = [bm.verts.new(p) for p in ((x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0))]
        fc = bm.faces.new(vs)
        for lp in fc.loops:
            lp[uvl].uv = self.uv_of(lp.vert.co.x, lp.vert.co.y)
        me = bpy.data.meshes.new("board")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(top)
        place(me, "board", outline=0)

        # land: one mesh, top triangles + walls
        bm = bmesh.new()
        uvl = bm.loops.layers.uv.new("UVMap")
        nfaces = 0
        for outer, holes in self.land:
            rings = [outer] + holes
            rings = [r for r in rings if len(r) >= 3]
            # orientation: outer CCW, holes CW
            fixed = []
            for i, r in enumerate(rings):
                a = signed_area(r)
                if (i == 0) != (a > 0):
                    r = r[::-1]
                fixed.append(r)
            try:
                tris = tessellate_polygon([[Vector((x, y, 0)) for x, y in r] for r in fixed])
            except Exception as e:
                print("[maps] tessellate failed", e)
                continue
            flat = [p for r in fixed for p in r]
            tv = [bm.verts.new((x, y, h)) for x, y in flat]
            for t in tris:
                a, b, c = (flat[i] for i in t)
                if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) < 0:
                    t = (t[0], t[2], t[1])
                try:
                    fc = bm.faces.new([tv[i] for i in t])
                except ValueError:
                    continue
                fc.material_index = 0
                nfaces += 1
            off = 0
            for r in fixed:
                n = len(r)
                bot = [bm.verts.new((x, y, 0)) for x, y in r]
                for i in range(n):
                    j = (i + 1) % n
                    ta, tb = tv[off + i], tv[off + j]
                    try:
                        fc = bm.faces.new((bot[i], bot[j], tb, ta))
                        fc.material_index = 1
                    except ValueError:
                        pass
                off += n
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        for fc in bm.faces:
            for lp in fc.loops:
                lp[uvl].uv = self.uv_of(lp.vert.co.x, lp.vert.co.y)
        me = bpy.data.meshes.new("land")
        bm.to_mesh(me)
        bm.free()
        me.materials.append(top)
        me.materials.append(wall)
        ob = place(me, "land", outline=0)
        b = ob.modifiers.new("bevel", "BEVEL")
        b.width = h * 0.32
        b.segments = 1
        b.limit_method = "ANGLE"
        b.angle_limit = math.radians(40)
        b.use_clamp_overlap = True
        b.harden_normals = False
        print(f"[maps] {self.rid}: land {nfaces} tris, {len(me.vertices)} verts", flush=True)

        # raised borders: thin tubes on the land
        bmat = toon("map_border", BORDER_HEX, bands=self.map_bands, haze=False)
        lines = []
        for line in self.borders:
            pts = []
            for x, y in line:
                px = int((x - x0) * self.ppu)
                py = int((y1 - y) * self.ppu)
                on = 0 <= px < self.TW and 0 <= py < self.TH and self.mask[py, px] > 0.5
                pts.append((x, y, h + 0.01 if on else 0.02))
            lines.append(pts)
        multi_tube("borders", lines, 0.055, bmat)

    def setup_camera(self, sc):
        cam_data = bpy.data.cameras.new("Cam")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = FRAME_W
        cam_data.sensor_fit = "HORIZONTAL"
        cam_data.clip_start = 1
        cam_data.clip_end = 500
        cam = bpy.data.objects.new("Cam", cam_data)
        sc.collection.objects.link(cam)
        sc.camera = cam
        cam.rotation_euler = (self.tilt, 0, 0)
        view = Vector((0, math.sin(self.tilt), -math.cos(self.tilt)))
        target = Vector((self.cx, self.cy, self.h))
        cam.location = target - view * 200
        sc.render.resolution_x = MAP_W
        sc.render.resolution_y = MAP_H
        bpy.context.view_layer.update()
        return cam

    def render(self):
        t0 = time.time()
        sc = reset_scene(samples=12)
        Ctx.haze = None
        Ctx.key = Vector((-0.55, 0.45, 0.72)).normalized()
        lz = Ctx.key.z
        self.map_bands = [(-2.0, 0.62), (0.05, 0.80), (lz - 0.12, 1.0), (lz + 0.06, 1.17)]
        self.load()
        self.paint()
        self.build()
        cam = self.setup_camera(sc)
        cities = {}
        for cid, lat, lon in self.cities:
            x, y = self.proj(lon, lat)
            co = world_to_camera_view(sc, cam, Vector((x, y, self.h)))
            cities[cid] = [round(co.x, 4), round(1 - co.y, 4)]
        raw = render_raw(sc, f"map_{self.rid}")
        img = Image.open(raw).convert("RGB")
        img = map_post(img)
        path = os.path.join(MAP_DIR, f"{self.rid}.jpg")
        size = save_jpeg(img, path, 85, 450)
        print(f"[maps] {self.rid}: {size // 1024} KB ({time.time() - t0:.1f}s)", flush=True)
        fx = [v[0] for v in cities.values()]
        fy = [v[1] for v in cities.values()]
        print(f"[maps] {self.rid}: city fx {min(fx):.3f}..{max(fx):.3f} "
              f"fy {min(fy):.3f}..{max(fy):.3f}", flush=True)
        return {"file": f"{self.rid}.jpg", "w": MAP_W, "h": MAP_H, "cities": cities}


def chain_edges(edges):
    """Join undirected segments into polylines."""
    adj = {}
    for a, b in edges:
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    used = set()
    lines = []

    def key(a, b):
        return (a, b) if a < b else (b, a)

    starts = [v for v, n in adj.items() if len(n) != 2] + list(adj)
    for s in starts:
        for nb in adj[s]:
            if key(s, nb) in used:
                continue
            line = [s, nb]
            used.add(key(s, nb))
            cur, prev = nb, s
            while len(adj[cur]) == 2:
                nxt = adj[cur][0] if adj[cur][1] == prev else adj[cur][1]
                if key(cur, nxt) in used:
                    break
                used.add(key(cur, nxt))
                line.append(nxt)
                prev, cur = cur, nxt
            lines.append(line)
    return lines


def map_post(img):
    """Soft vignette like a lamp-lit war table."""
    W, H = img.size
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dx = (xx - W / 2) / (W / 2)
    dy = (yy - H / 2) / (H / 2)
    r = np.sqrt(dx * dx * 0.8 + dy * dy * 0.9)
    v = 1 - 0.22 * np.clip((r - 0.55) / 0.75, 0, 1) ** 1.6
    a = np.asarray(img, np.float32) * v[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def render_map(rid):
    return MapBuilder(rid).render()


# ==========================================================================
# BACKDROPS
# ==========================================================================
BG_W, BG_H = 1600, 900
SUN_K = 0.3683          # Cycles: white diffuse under a strength-1 sun
STRIP = 0.32            # bottom fraction of the frame kept as open ground


def M(hx, **kw):
    """Cached toon material named after its arguments."""
    key = "t_" + hx + "_" + "_".join(f"{k}{v}" for k, v in sorted(kw.items()))
    return toon(key[:60] + str(abs(hash(key)) % 9973), hx, **kw)


def toon_snow(base, snow="#e9eef0", thr=0.55):
    """Toon material whose up-facing faces carry snow."""
    key = ("snow", base, snow, thr)
    if key in _MAT_CACHE:
        return _MAT_CACHE[key]
    m, nt = _new_mat(f"snow_{base}_{thr}")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], sep.inputs[0])
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 2.5
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "MULTIPLY_ADD"
    add.inputs[1].default_value = 0.35
    nt.links.new(noise.outputs["Fac"], add.inputs[0])
    nt.links.new(sep.outputs["Z"], add.inputs[2])
    stp = nt.nodes.new("ShaderNodeMath")
    stp.operation = "GREATER_THAN"
    stp.inputs[1].default_value = thr + 0.17
    nt.links.new(add.outputs[0], stp.inputs[0])
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    nt.links.new(stp.outputs[0], _sock(mix.inputs, "Factor_Float"))
    _sock(mix.inputs, "A_Color").default_value = hexcol(base)
    _sock(mix.inputs, "B_Color").default_value = hexcol(snow)
    band = _band_ramp(nt, geo.outputs["Normal"], Ctx.bands, Ctx.key)
    _, col = _mul(nt, _sock(mix.outputs, "Result_Color"), band)
    if Ctx.haze:
        hx, near, far, mx = Ctx.haze[:4]
        fac = _haze_fac(nt, near, far, mx, Ctx.haze[4] if len(Ctx.haze) > 4 else 1.0)
        mh = nt.nodes.new("ShaderNodeMix")
        mh.data_type = "RGBA"
        nt.links.new(fac, _sock(mh.inputs, "Factor_Float"))
        nt.links.new(col, _sock(mh.inputs, "A_Color"))
        _sock(mh.inputs, "B_Color").default_value = hexcol(hx)
        col = _sock(mh.outputs, "Result_Color")
    nt.links.new(col, em.inputs["Color"])
    _MAT_CACHE[key] = m
    return m


def MS(hx, snow=None, thr=0.55):
    """Material for props: snow-capped when the scene is snowy."""
    if Ctx.snowy and snow is not False:
        return toon_snow(hx, thr=thr)
    return M(hx)


def zband_mat(name, bands_z, haze=True):
    """Toon material coloured by object-space height: [(z, hex), ...]."""
    key = (name,)
    if key in _MAT_CACHE:
        return _MAT_CACHE[key]
    m, nt = _new_mat(name)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    tc = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Object"], sep.inputs[0])
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 0.02
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "MULTIPLY_ADD"
    add.inputs[1].default_value = 40.0
    nt.links.new(noise.outputs["Fac"], add.inputs[0])
    nt.links.new(sep.outputs["Z"], add.inputs[2])
    z0, z1 = bands_z[0][0], bands_z[-1][0]
    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.inputs["From Min"].default_value = z0 + 20
    mr.inputs["From Max"].default_value = z1 + 20
    nt.links.new(add.outputs[0], mr.inputs["Value"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = "CONSTANT"
    els = ramp.color_ramp.elements
    els[0].position = 0.0
    els[0].color = hexcol(bands_z[0][1])
    els[1].position = (bands_z[1][0] - z0) / (z1 - z0)
    els[1].color = hexcol(bands_z[1][1])
    for z, hx in bands_z[2:]:
        e = els.new(min(0.999, (z - z0) / (z1 - z0)))
        e.color = hexcol(hx)
    nt.links.new(mr.outputs["Result"], ramp.inputs["Fac"])
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    band = _band_ramp(nt, geo.outputs["Normal"], Ctx.bands, Ctx.key)
    _, col = _mul(nt, ramp.outputs["Color"], band)
    if haze and Ctx.haze:
        hx, near, far, mx = Ctx.haze[:4]
        fac = _haze_fac(nt, near, far, mx, Ctx.haze[4] if len(Ctx.haze) > 4 else 1.0)
        mh = nt.nodes.new("ShaderNodeMix")
        mh.data_type = "RGBA"
        nt.links.new(fac, _sock(mh.inputs, "Factor_Float"))
        nt.links.new(col, _sock(mh.inputs, "A_Color"))
        _sock(mh.inputs, "B_Color").default_value = hexcol(hx)
        col = _sock(mh.outputs, "Result_Color")
    nt.links.new(col, em.inputs["Color"])
    _MAT_CACHE[key] = m
    return m


class Batch:
    """Many primitives merged into one mesh/object (one hull per batch)."""

    def __init__(self, name, mats, outline=1.0, push=True):
        self.push = push
        self.bm = bmesh.new()
        self.name = name
        self.mats = mats if isinstance(mats, (list, tuple)) else [mats]
        self.outline = outline

    def _tag(self, verts, mi):
        if mi == 0:
            return
        faces = set()
        for v in verts:
            faces.update(v.link_faces)
        for f in faces:
            f.material_index = mi

    @staticmethod
    def _mat(loc, rot, scale):
        R = Matrix.Identity(4)
        if rot is not None:
            from mathutils import Euler
            R = Euler([math.radians(a) for a in rot], "XYZ").to_matrix().to_4x4()
        return Matrix.Translation(Vector(loc)) @ R @ Matrix.Diagonal(tuple(scale) + (1,))

    def box(self, size, loc, rot=None, mi=0):
        r = bmesh.ops.create_cube(self.bm, size=1.0, matrix=self._mat(loc, rot, size))
        self._tag(r["verts"], mi)
        return r["verts"]

    def cone(self, r1, r2, depth, loc, rot=None, segs=8, mi=0, scale=(1, 1, 1), base=True):
        """Cone/cylinder; loc is the base centre when base=True."""
        T = self._mat(loc, rot, scale) @ Matrix.Translation((0, 0, depth / 2 if base else 0))
        r = bmesh.ops.create_cone(self.bm, cap_ends=True, cap_tris=False, segments=segs,
                                  radius1=r1, radius2=r2, depth=depth, matrix=T)
        self._tag(r["verts"], mi)
        return r["verts"]

    def ico(self, r, loc, scale=(1, 1, 1), rot=None, sub=1, mi=0, jitter=0.0, rnd=None):
        res = bmesh.ops.create_icosphere(self.bm, subdivisions=sub, radius=r,
                                         matrix=self._mat(loc, rot, scale))
        if jitter:
            rnd = rnd or random
            c = Vector(loc)
            for v in res["verts"]:
                v.co = c + (v.co - c) * (1 + rnd.uniform(-jitter, jitter))
        self._tag(res["verts"], mi)
        return res["verts"]

    def prism(self, pts, a0, a1, axis="y", mi=0, loc=(0, 0, 0), rot=None):
        """Extrude a 2D profile.  axis='y': pts are (x, z); axis='x': (y, z)."""
        T = self._mat(loc, rot, (1, 1, 1))
        if axis == "y":
            f = [T @ Vector((u, a0, v)) for u, v in pts]
            b = [T @ Vector((u, a1, v)) for u, v in pts]
        else:
            f = [T @ Vector((a0, u, v)) for u, v in pts]
            b = [T @ Vector((a1, u, v)) for u, v in pts]
        bm = self.bm
        fv = [bm.verts.new(p) for p in f]
        bv = [bm.verts.new(p) for p in b]
        faces = [bm.faces.new(fv), bm.faces.new(list(reversed(bv)))]
        n = len(pts)
        for i in range(n):
            j = (i + 1) % n
            faces.append(bm.faces.new((fv[i], fv[j], bv[j], bv[i])))
        for fc in faces:
            fc.material_index = mi
        return fv + bv

    def quad_strip(self, rows, mi=0):
        """Grid surface from rows of 3D points (equal lengths)."""
        bm = self.bm
        vr = [[bm.verts.new(p) for p in row] for row in rows]
        for r0, r1 in zip(vr[:-1], vr[1:]):
            for i in range(len(r0) - 1):
                fc = bm.faces.new((r0[i], r0[i + 1], r1[i + 1], r1[i]))
                fc.material_index = mi

    def bar(self, p0, p1, w, mi=0, d=None):
        p0, p1 = Vector(p0), Vector(p1)
        v = p1 - p0
        q = v.normalized().to_track_quat("Z", "Y")
        T = Matrix.Translation((p0 + p1) / 2) @ q.to_matrix().to_4x4() @ \
            Matrix.Diagonal((w, d or w, v.length, 1))
        r = bmesh.ops.create_cube(self.bm, size=1.0, matrix=T)
        self._tag(r["verts"], mi)

    def finish(self, smooth=False, outline=None, recalc=True):
        if not self.bm.verts:
            self.bm.free()
            return None
        if recalc:
            bmesh.ops.recalc_face_normals(self.bm, faces=self.bm.faces)
        if self.push and Ctx.push:
            y0, off = Ctx.push
            for v in self.bm.verts:
                if v.co.y > y0:
                    v.co.y += off
        cen = Vector((0, 0, 0))
        for v in self.bm.verts:
            cen += v.co
        cen /= len(self.bm.verts)
        me = bpy.data.meshes.new(self.name)
        self.bm.to_mesh(me)
        self.bm.free()
        if smooth or self.name.startswith("smoke"):
            me.polygons.foreach_set("use_smooth", [True] * len(me.polygons))
        for m in self.mats:
            me.materials.append(m)
        ol = self.outline if outline is None else outline
        ob = bpy.data.objects.new(self.name, me)
        bpy.context.scene.collection.objects.link(ob)
        th = _hull_thickness(cen, ol)
        if th > 0:
            me.materials.append(outline_mat())
            s = ob.modifiers.new("outline", "SOLIDIFY")
            s.thickness = th
            s.offset = 1.0
            s.use_flip_normals = True
            s.use_even_offset = False
            s.use_rim = False
            s.material_offset = len(me.materials) - 1
        Ctx.objects.append(ob)
        return ob


# --------------------------------------------------------------------------
# camera / ground / sky
# --------------------------------------------------------------------------
class Cam:
    h = 2.2
    pitch = 2.0
    lens = 40.0
    x = 0.0


def bd_camera(sc):
    cd = bpy.data.cameras.new("Cam")
    cd.lens = Cam.lens
    cd.sensor_width = 36
    cd.sensor_fit = "HORIZONTAL"
    cd.clip_start = 0.2
    cd.clip_end = 6000
    cam = bpy.data.objects.new("Cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.location = (Cam.x, 0, Cam.h)
    cam.rotation_euler = (math.radians(90 - Cam.pitch), 0, 0)
    sc.render.resolution_x = BG_W
    sc.render.resolution_y = BG_H
    bpy.context.view_layer.update()
    Ctx.cam_pos = Vector(cam.location)
    return cam


def frame_geom():
    """Vertical half-FOV and the ground distance at the strip top."""
    hf = math.atan(36 / 2 / Cam.lens * BG_H / BG_W)
    t = math.tan(hf)

    def y_at(frac_from_top):
        a = math.atan((frac_from_top - 0.5) * 2 * t) + math.radians(Cam.pitch)
        return Cam.h / math.tan(a) if a > 0 else 1e9
    return hf, y_at


def half_width(y):
    return y * 36 / 2 / Cam.lens + 2.0


def ground(mat, height=None, y_max=2600.0, cols=90, name="ground", flat_until=24.0,
           x_extra=1.25):
    """Trapezoid grid covering the view; height(x, y) applied beyond flat_until."""
    ys = [2.0]
    while ys[-1] < y_max:
        ys.append(ys[-1] * 1.07 + 0.4)
    bt = Batch(name, mat, outline=0, push=False)
    rows = []
    for y in ys:
        hw = half_width(y) * x_extra + 6
        row = []
        for i in range(cols + 1):
            x = Cam.x - hw + 2 * hw * i / cols
            z = 0.0
            if height and y > flat_until:
                z = height(x, y)
            row.append((x, y, z))
        rows.append(row)
    bt.quad_strip(rows)
    ob = bt.finish(recalc=False)
    return ob


def sun_for(key, shadow):
    """Sun lamp matching the toon key so flat lit ground = base colour."""
    k = Vector(key).normalized()
    strength = (1 - shadow) / (SUN_K * max(k.z, 0.05))
    return add_sun(k, strength, angle=0.3)


def lerp_hex(stops, t):
    for (p0, c0), (p1, c1) in zip(stops[:-1], stops[1:]):
        if t <= p1:
            u = (t - p0) / max(p1 - p0, 1e-6)
            return tuple(a + (b - a) * u for a, b in zip(hex_rgb(c0), hex_rgb(c1)))
    return hex_rgb(stops[-1][1])


def paint_sky(cfg, seed):
    W, H = BG_W, BG_H
    stops = cfg["sky"]
    col = np.array([lerp_hex(stops, y / (H - 1)) for y in range(H)], np.float32)
    img = np.repeat(col[:, None, :], W, axis=1)
    rnd = random.Random(seed)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    sun = cfg.get("sun")
    if sun:
        sx, sy, r, hx, st = sun
        d = np.sqrt((xx - sx * W) ** 2 + (yy - sy * H) ** 2) / (r * W)
        glow = np.clip(1 - d, 0, 1) ** 2.2 * st
        img = img + (np.array(hex_rgb(hx), np.float32) - img) * glow[..., None]
        disc = (d < 0.09).astype(np.float32)
        img = img + (np.array((255, 238, 200), np.float32) - img) * disc[..., None] * 0.85
    if cfg.get("stars"):
        sky = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(sky)
        for _ in range(420):
            x, y = rnd.uniform(0, W), rnd.uniform(0, H * 0.55) ** 1.0
            b = rnd.uniform(0.35, 1.0) * (1 - y / (H * 0.6))
            r = 1.6 if rnd.random() < 0.08 else 0.8
            c = tuple(int(v + (255 - v) * b) for v in hex_rgb(stops[0][1]))
            d.ellipse((x - r, y - r, x + r, y + r), fill=c)
        img = np.asarray(sky, np.float32)
    sky = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
    for layer in cfg.get("clouds", []):
        sky = paint_clouds(sky, layer, rnd)
    return sky


def paint_clouds(sky, layer, rnd):
    """Toon cloud banks: union of ellipses, three flat tones (shadowed
    base, body, lit crown), soft edges."""
    W, H = sky.size
    y0, y1, n, size, shade, lit, alpha = layer
    body = tuple(int(a * 0.55 + b * 0.45) for a, b in zip(shade, lit))
    shape = Image.new("L", (W, H), 0)
    for _ in range(n):
        one = Image.new("L", (W, H), 0)
        ds = ImageDraw.Draw(one)
        cx = rnd.uniform(-0.1, 1.1) * W
        cy = rnd.uniform(y0, y1) * H
        w = rnd.uniform(0.6, 1.4) * size * W
        h = w * rnd.uniform(0.16, 0.26)
        for _ in range(rnd.randint(5, 9)):
            ox = rnd.uniform(-0.5, 0.5) * w
            r = rnd.uniform(0.12, 0.28) * w * (1.2 - abs(ox) / w)
            oy = rnd.uniform(-0.3, 0.1) * h
            ds.ellipse((cx + ox - r, cy + oy - r * 0.7, cx + ox + r, cy + oy + r * 0.7), fill=255)
        shape = ImageChops.lighter(shape, one)
    shape = shape.filter(ImageFilter.GaussianBlur(1.5))
    off = max(4, int(size * W * 0.045))
    lower = ImageChops.offset(shape, 0, -off)          # shape shifted up
    shadow = ImageChops.subtract(shape, lower)          # bottom band
    upper = ImageChops.offset(shape, int(off * 0.6), off)
    crown = ImageChops.subtract(shape, upper)           # top-left band
    out = Image.composite(Image.new("RGB", (W, H), body), sky, shape.point(lambda v: int(v * alpha)))
    out = Image.composite(Image.new("RGB", (W, H), shade), out, shadow.point(lambda v: int(v * alpha)))
    out = Image.composite(Image.new("RGB", (W, H), lit), out, crown.point(lambda v: int(v * alpha)))
    return out.filter(ImageFilter.GaussianBlur(0.6)) if False else out


def bloom(img, thr=0.82, radius=18, amount=0.55):
    a = np.asarray(img, np.float32) / 255
    lum = a.max(axis=2)
    m = np.clip((lum - thr) / (1 - thr), 0, 1)
    src = Image.fromarray((a * m[..., None] * 255).astype(np.uint8))
    b = np.asarray(src.filter(ImageFilter.GaussianBlur(radius)), np.float32) / 255
    out = 1 - (1 - a) * (1 - b * amount)
    return Image.fromarray(np.clip(out * 255, 0, 255).astype(np.uint8))


def grade(img, cfg):
    W, H = img.size
    a = np.asarray(img, np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    dx = (xx - W / 2) / (W / 2)
    dy = (yy - H * 0.45) / (H / 2)
    r = np.sqrt(dx * dx * 0.7 + dy * dy * 0.8)
    v = 1 - cfg.get("vignette", 0.22) * np.clip((r - 0.5) / 0.8, 0, 1) ** 1.5
    a = a * v[..., None]
    tint = cfg.get("tint")
    if tint:
        hx, amt = tint
        a = a * (1 - amt) + a * np.array(hex_rgb(hx), np.float32) / 255 * amt * 1.6
    rng = np.random.default_rng(7)
    a = a + rng.normal(0, 2.0, a.shape[:2])[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# --------------------------------------------------------------------------
# props
# --------------------------------------------------------------------------
def tree_round(bt, x, y, s, rnd, trunk_mi=0, leaf_mi=1, blobs=3):
    h = s * rnd.uniform(1.6, 2.2)
    bt.cone(0.12 * s, 0.08 * s, h, (x, y, 0), segs=6, mi=trunk_mi)
    for i in range(blobs):
        ox, oy = rnd.uniform(-0.45, 0.45) * s, rnd.uniform(-0.3, 0.3) * s
        r = s * rnd.uniform(0.75, 1.05) * (1 - i * 0.12)
        bt.ico(r, (x + ox, y + oy, h + r * 0.35 + i * 0.35 * s),
               scale=(1, 1, rnd.uniform(0.75, 0.95)), mi=leaf_mi, jitter=0.12, rnd=rnd)


def pine(bt, x, y, s, rnd, trunk_mi=0, leaf_mi=1, tiers=4):
    bt.cone(0.1 * s, 0.07 * s, 1.0 * s, (x, y, 0), segs=6, mi=trunk_mi)
    z = 0.6 * s
    r = 1.0 * s * rnd.uniform(0.9, 1.1)
    for i in range(tiers):
        hh = 1.5 * s * (1 - i * 0.1)
        bt.cone(r, r * 0.12, hh, (x, y, z), segs=7, mi=leaf_mi,
                rot=(0, 0, rnd.uniform(0, 60)))
        z += hh * 0.55
        r *= 0.76


def bamboo_clump(bt, x, y, s, rnd, cane_mi=0, leaf_mi=1, n=12):
    for _ in range(n):
        cx, cy = x + rnd.gauss(0, 0.8 * s), y + rnd.gauss(0, 0.6 * s)
        hgt = s * rnd.uniform(7, 11)
        lean = (rnd.uniform(-7, 7), rnd.uniform(-5, 5), 0)
        bt.cone(0.07 * s, 0.05 * s, hgt, (cx, cy, 0), segs=5, mi=cane_mi, rot=lean)
        top = Vector((cx, cy, 0)) + (Matrix.Rotation(math.radians(lean[0]), 3, "X") @
                                     Matrix.Rotation(math.radians(lean[1]), 3, "Y") @
                                     Vector((0, 0, hgt)))
        for k in range(rnd.randint(4, 7)):
            t = rnd.uniform(0.45, 1.0)
            p = Vector((cx, cy, 0)).lerp(top, t)
            bt.ico(0.55 * s, p + Vector((rnd.uniform(-0.6, 0.6) * s, rnd.uniform(-0.3, 0.3) * s, 0)),
                   scale=(1.5, 0.8, 0.35), rot=(0, rnd.uniform(-35, 35), rnd.uniform(0, 180)),
                   mi=leaf_mi, jitter=0.2, rnd=rnd)


def palm(bt, x, y, s, rnd, trunk_mi=0, leaf_mi=1):
    hgt = s * rnd.uniform(5, 7.5)
    bend = rnd.uniform(-1.2, 1.2) * s
    pts = [Vector((x + bend * (t / 4) ** 2, y, hgt * t / 4)) for t in range(5)]
    for a, b in zip(pts[:-1], pts[1:]):
        bt.bar(a, b, 0.22 * s, mi=trunk_mi)
    top = pts[-1]
    for k in range(9):
        ang = k * 40 + rnd.uniform(-12, 12)
        L = s * rnd.uniform(2.4, 3.2)
        d = Vector((math.cos(math.radians(ang)), math.sin(math.radians(ang)) * 0.7, 0))
        for j in range(3):
            t = (j + 0.6) / 3
            p = top + d * L * t + Vector((0, 0, (0.5 * t - 1.3 * t * t) * s))
            bt.ico(L * 0.2, p, scale=(1.9, 0.6, 0.18), rot=(0, 25 + 45 * t, ang), mi=leaf_mi, sub=1)


def shrub(bt, x, y, s, rnd, mi=0, n=3):
    for _ in range(n):
        bt.ico(s * rnd.uniform(0.6, 1.0), (x + rnd.uniform(-0.8, 0.8) * s, y + rnd.uniform(-0.4, 0.4) * s,
                                            s * 0.35), scale=(1.2, 1, 0.75), mi=mi, jitter=0.15, rnd=rnd)


def rubble(bt, x, y, w, rnd, n=40, h=1.0, mis=(0,), scale=1.0):
    for _ in range(n):
        dx = rnd.gauss(0, w * 0.35)
        hh = max(0.0, h * (1 - abs(dx) / (w * 0.7)))
        sz = rnd.uniform(0.25, 0.7) * scale
        bt.box((sz * rnd.uniform(0.8, 1.6), sz, sz * rnd.uniform(0.4, 0.8)),
               (x + dx, y + rnd.gauss(0, 0.8), rnd.uniform(0, hh)),
               rot=(rnd.uniform(-30, 30), rnd.uniform(-30, 30), rnd.uniform(0, 90)),
               mi=rnd.choice(mis))


def pole_line(xs, y, hgt, wood, wire_mat, rnd, name="poles", sag=0.5):
    bt = Batch(name, [wood], outline=1.0)
    tops = []
    for x in xs:
        lean = rnd.uniform(-3, 3)
        bt.cone(0.13, 0.1, hgt, (x, y, 0), segs=6, rot=(0, lean, 0))
        tx = x + math.sin(math.radians(lean)) * hgt
        bt.box((2.0, 0.14, 0.14), (tx, y, hgt - 0.5), rot=(0, lean, 0))
        for k in (-0.8, -0.3, 0.3, 0.8):
            bt.cone(0.04, 0.04, 0.16, (tx + k, y, hgt - 0.43), segs=5)
        tops.append(tx)
    bt.finish()
    lines = []
    for k in (-0.8, -0.3, 0.3, 0.8):
        for a, b in zip(tops[:-1], tops[1:]):
            pts = []
            for i in range(13):
                t = i / 12
                pts.append((a + k + (b - a) * t, y, hgt - 0.3 - sag * 4 * t * (1 - t)))
            lines.append(pts)
    multi_tube(name + "_wires", lines, 0.022, wire_mat)


def gable_house(bt, x, y, w, d, h, rh, wall_mi, roof_mi, ridge="x", over=0.35):
    """Box body + gable roof; ridge along x (long side faces camera)."""
    bt.box((w, d, h), (x, y, h / 2), mi=wall_mi)
    if ridge == "x":
        pts = [(-d / 2 - over, 0), (d / 2 + over, 0), (0, rh)]
        bt.prism(pts, x - w / 2 - over * 0.6, x + w / 2 + over * 0.6, axis="x",
                 mi=roof_mi, loc=(0, y, h))
    else:
        pts = [(-w / 2 - over, 0), (w / 2 + over, 0), (0, rh)]
        bt.prism(pts, y - d / 2 - over * 0.6, y + d / 2 + over * 0.6, axis="y",
                 mi=roof_mi, loc=(x, 0, h))


def windows_row(bt, x0, x1, z, y_face, n, ww, wh, mi, frame_mi=None, rnd=None, broken=0.0):
    if n <= 0:
        return
    step = (x1 - x0) / n
    for i in range(n):
        cx = x0 + step * (i + 0.5)
        bt.box((ww, 0.12, wh), (cx, y_face - 0.04, z), mi=mi)
        if frame_mi is not None and (rnd is None or rnd.random() > broken):
            bt.box((ww + 0.16, 0.14, 0.1), (cx, y_face - 0.06, z - wh / 2 - 0.05), mi=frame_mi)
            bt.box((0.07, 0.15, wh), (cx, y_face - 0.07, z), mi=frame_mi)


def mountains(name, y, x_span, peak_h, rnd, mat, n=26, depth=None, base=-8.0, jag=0.45):
    """Low-poly ridge: front foot, crest, back foot rows -> faceted slopes."""
    depth = depth or peak_h * 2.6
    xs = np.linspace(Cam.x - x_span, Cam.x + x_span, n)
    crest = []
    hgt = peak_h * 0.6
    for i, x in enumerate(xs):
        hgt = max(peak_h * 0.2, min(peak_h, hgt + rnd.uniform(-jag, jag) * peak_h))
        crest.append(hgt)
    bt = Batch(name, [mat], outline=0)
    front, mid, mid2, back = [], [], [], []
    for x, hc in zip(xs, crest):
        jx = rnd.uniform(-0.3, 0.3) * (xs[1] - xs[0])
        front.append((x, y - depth * 0.5, base))
        mid.append((x + jx, y - depth * 0.18, hc * rnd.uniform(0.45, 0.7)))
        mid2.append((x + jx * 0.5, y, hc))
        back.append((x, y + depth * 0.5, base))
    bt.quad_strip([front, mid, mid2, back])
    return bt.finish(recalc=False)


def smoke(bt, x, y, h, rnd, mi=0, n=9, s=1.0, drift=1.0):
    """Billowing plume: blobs spreading wider with height, leaning downwind."""
    for i in range(n):
        t = i / (n - 1)
        r = s * (1.0 + 1.3 * t)
        cx = x + drift * t * t * h * 0.7
        cz = h * t + r * 0.4
        for k in range(1 + int(t * 3)):
            ox = rnd.uniform(-1, 1) * r * (0.5 + 1.5 * t)
            rr = r * rnd.uniform(0.75, 1.1)
            res = bmesh.ops.create_uvsphere(
                bt.bm, u_segments=14, v_segments=8, radius=rr,
                matrix=Batch._mat((cx + ox, y + rnd.uniform(-1, 1) * r, cz + rnd.uniform(-0.4, 0.4) * r),
                                  None, (1.25, 1, 0.85)))
            bt._tag(res["verts"], rnd.randint(0, 1) if mi == 0 else mi)


def fence(bt, x0, x1, y, rnd, mi=0, h=1.1, gap=2.2, broken=0.15):
    x = x0
    while x < x1:
        if rnd.random() > broken:
            bt.box((0.12, 0.12, h), (x, y, h / 2), rot=(rnd.uniform(-6, 6), rnd.uniform(-8, 8), 0), mi=mi)
            if x + gap < x1 and rnd.random() > broken:
                for zz in (h * 0.45, h * 0.85):
                    bt.box((gap, 0.06, 0.12), (x + gap / 2, y - 0.07, zz + rnd.uniform(-0.05, 0.05)),
                           rot=(0, rnd.uniform(-3, 3), 0), mi=mi)
        x += gap


def strip_mesh(name, pts, width, mat, z=0.02, outline=0):
    """Flat ribbon along an XY polyline (roads, rivers, ruts)."""
    bt = Batch(name, [mat], outline=outline)
    rows_l, rows_r = [], []
    for i, p in enumerate(pts):
        a = Vector(pts[max(i - 1, 0)])
        b = Vector(pts[min(i + 1, len(pts) - 1)])
        t = (b - a).normalized()
        nrm = Vector((-t.y, t.x)) * (width / 2 if not hasattr(width, "__call__") else width(i) / 2)
        rows_l.append((p[0] + nrm.x, p[1] + nrm.y, z))
        rows_r.append((p[0] - nrm.x, p[1] - nrm.y, z))
    bt.quad_strip([rows_r, rows_l])
    return bt.finish(recalc=False)


# --------------------------------------------------------------------------
# scenes
# --------------------------------------------------------------------------
def hills_fn(rnd, amp=6.0, start=60.0, ramp=120.0, scale=1.0):
    bumps = [(rnd.uniform(-900, 900), rnd.uniform(100, 1400), rnd.uniform(40, 160) * scale,
              rnd.uniform(0.3, 1.0)) for _ in range(70)]

    def f(x, y):
        m = min(1.0, max(0.0, (y - start) / ramp))
        z = 0.0
        for bx, by, r, a in bumps:
            d2 = ((x - bx) ** 2 + (y - by) ** 2) / (r * r)
            if d2 < 9:
                z += a * math.exp(-d2)
        z += 0.3 * math.sin(x * 0.013 + 1.3) * math.sin(y * 0.011)
        return z * amp * m * (1 + y / 600)
    return f


def grass_clumps(bt, x0, x1, y0, y1, n, rnd, mis, s=1.0):
    for _ in range(n):
        x, y = rnd.uniform(x0, x1), rnd.uniform(y0, y1)
        for k in range(rnd.randint(3, 5)):
            ang = rnd.uniform(0, 360)
            bt.box((0.07 * s, 0.07 * s, rnd.uniform(0.35, 0.7) * s),
                   (x + rnd.uniform(-0.15, 0.15) * s, y + rnd.uniform(-0.1, 0.1) * s, 0.2 * s),
                   rot=(rnd.uniform(-25, 25), rnd.uniform(-25, 25), ang), mi=rnd.choice(mis))


def corn_stalk(bt, x, y, rnd, mis=(0, 1, 2)):
    hgt = rnd.uniform(2.1, 2.6)
    bt.cone(0.05, 0.03, hgt, (x, y, 0), segs=4, mi=mis[0])
    for k in range(4):
        zz = hgt * (0.3 + 0.15 * k)
        ang = rnd.uniform(0, 360)
        c, s_ = math.cos(math.radians(ang)), math.sin(math.radians(ang))
        bt.box((0.75, 0.2, 0.03), (x + 0.33 * c, y + 0.33 * s_, zz),
               rot=(0, 28 + rnd.uniform(-8, 12), ang), mi=mis[rnd.randint(0, 1)])
    bt.box((0.09, 0.09, 0.42), (x, y, hgt + 0.18), mi=mis[2])


def scene_us_farm(rnd):
    s = {}
    wood = M("#6b5640")
    g = ground_mat("g_farm", "#8a8a4c", [(0.4, "#7d8045"), (0.55, "#958f52"), (0.7, "#a39a5c")],
                   patch_scale=0.03)
    ground(g, hills_fn(rnd, amp=6.0, start=90))
    road = ground_mat("g_road", "#9c8460", [(0.45, "#8f7756"), (0.62, "#a68d66")], patch_scale=0.35)
    rd = lambda x: 12.4 + 0.4 * math.sin(x * 0.05)  # noqa: E731
    strip_mesh("road", [(x, rd(x), 0) for x in range(-40, 41, 2)], 5.4, road)
    rut = ground_mat("g_rut", "#7f6a4a", patch_scale=0.5)
    for off in (-1.15, 1.05):
        strip_mesh("rut", [(x, rd(x) + off, 0) for x in range(-40, 41, 2)], 0.42, rut, z=0.03)
    bt = Batch("tufts", [M("#6f7a3e"), M("#8d8c4b"), M("#a39a58")], outline=0)
    grass_clumps(bt, -30, 30, 19.2, 23.5, 120, rnd, (0, 1, 2), s=0.7)
    bt.finish()
    bt = Batch("fence", [wood], outline=0.8)
    fence(bt, -40, 40, 23.0, rnd, broken=0.18)
    bt.finish()
    pole_line([-58, -36, -14, 8, 30, 52], 44.0, 8.0, wood, M("#2b2620"), rnd, sag=0.7)
    # red barn (gambrel) + silo, left midground
    bt = Batch("barn", [M("#9c3b2c", patches=[(0.55, "#953829")], patch_scale=1.5),
                        M("#4b4a46"), M("#e8dcc0"), M("#2a1d17")])
    bx, by, bw, bd, bh = -19.0, 72.0, 13.0, 11.0, 5.0
    bt.box((bw, bd, bh), (bx, by, bh / 2))
    prof = [(-bd / 2 - 0.4, 0), (bd / 2 + 0.4, 0), (bd / 2 - 0.6, 2.4), (1.0, 4.4), (-1.0, 4.4),
            (-bd / 2 + 0.6, 2.4)]
    bt.prism(prof, bx - bw / 2 - 0.3, bx + bw / 2 + 0.3, axis="x", mi=1, loc=(0, by, bh))
    f = by - bd / 2
    bt.box((4.2, 0.2, 4.0), (bx, f - 0.05, 2.0), mi=3)
    for xo in (-2.1, 2.1):
        bt.box((0.24, 0.26, 4.1), (bx + xo, f - 0.08, 2.05), mi=2)
    bt.box((4.4, 0.26, 0.24), (bx, f - 0.08, 4.1), mi=2)
    bt.bar((bx - 2.0, f - 0.12, 0.2), (bx + 2.0, f - 0.12, 3.95), 0.22, mi=2)
    bt.bar((bx + 2.0, f - 0.12, 0.2), (bx - 2.0, f - 0.12, 3.95), 0.22, mi=2)
    bt.box((1.6, 0.2, 1.2), (bx, f - 0.05, 6.8), mi=3)
    bt.box((1.9, 0.24, 0.18), (bx, f - 0.08, 6.15), mi=2)
    windows_row(bt, bx - bw / 2 + 0.6, bx - 2.6, 3.0, f, 2, 0.9, 1.0, 3, 2)
    windows_row(bt, bx + 2.6, bx + bw / 2 - 0.6, 3.0, f, 2, 0.9, 1.0, 3, 2)
    # lean-to shed
    bt.box((5, 7, 3.0), (bx + bw / 2 + 2.5, by + 1, 1.5), mi=0)
    bt.prism([(-3.7, 0), (3.7, 0), (-3.7, 1.4)], bx + bw / 2, bx + bw / 2 + 5.3, axis="x", mi=1,
             loc=(0, by + 1, 3.0))
    bt.finish()
    bt = Batch("silo", [M("#b9b3a2", patches=[(0.6, "#b2ac9b")], patch_scale=1.2), M("#7c8286"),
                        M("#8a3a2c")])
    sx, sy = -6.5, 80.0
    bt.cone(2.5, 2.5, 12.0, (sx, sy, 0), segs=16)
    for k in range(1, 6):
        bt.cone(2.58, 2.58, 0.18, (sx, sy, k * 2.0), segs=16, mi=2)
    res = bmesh.ops.create_uvsphere(bt.bm, u_segments=16, v_segments=8, radius=2.55,
                                    matrix=Matrix.Translation((sx, sy, 12.0)))
    for v in res["verts"]:
        v.co.z = max(v.co.z, 12.0)
    bt._tag(res["verts"], 1)
    bt.finish(smooth=True)
    bt = Batch("bales", [M("#c7a85e"), M("#b19450")])
    for i in range(6):
        x, y = -34 + i * 2.6 + rnd.uniform(-0.5, 0.5), rnd.uniform(42, 52)
        bt.cone(0.8, 0.8, 1.5, (x, y, 0.8), rot=(0, 90, rnd.uniform(-30, 30)), segs=10, base=False,
                mi=i % 2)
    bt.finish(smooth=True)
    # cornfield on the right: rows running away from the camera
    cm = [M("#6c7a3a"), M("#86883f"), M("#c3a557")]
    near = Batch("corn_near", cm, outline=0.55)
    far = Batch("corn_far", cm, outline=0)
    for r in range(24):
        x = 7.5 + r * 1.6
        y = 31.0
        while y < 115:
            corn_stalk(near if y < 55 else far, x + rnd.uniform(-0.15, 0.15), y, rnd)
            y += rnd.uniform(0.7, 0.95) * (1 + (y - 31) / 35)
    near.finish()
    far.finish()
    bt = Batch("trees_mid", [M("#5a4a38"), M("#66733e"), M("#5b6a39")], outline=0.8)
    for x, y in ((-46, 90), (-38, 98), (14, 150), (24, 144), (-60, 120), (2, 160)):
        tree_round(bt, x, y, rnd.uniform(2.8, 3.8), rnd, leaf_mi=1 + rnd.randint(0, 1))
    bt.finish()
    bt = Batch("trees_far", [M("#5a4a38"), M("#5f6d3a"), M("#68733f")], outline=0)
    for i in range(40):
        tree_round(bt, rnd.uniform(-200, 200), rnd.uniform(220, 300), rnd.uniform(4, 6), rnd,
                   leaf_mi=1 + i % 2)
    bt.finish()
    bt = Batch("farm_far", [M("#d8ccb0"), M("#5b5650"), M("#9c3b2c")], outline=0)
    gable_house(bt, 70, 260, 12, 8, 5, 3.5, 0, 1)
    bt.cone(2.4, 2.4, 12, (82, 266, 0), segs=12)
    gable_house(bt, -110, 320, 14, 10, 5, 4, 2, 1)
    bt.finish()
    bt = Batch("smoke", [M("#6d655e"), M("#857b70")], outline=0)
    smoke(bt, 260, 1100, 150, rnd, n=8, s=12.0, drift=0.4)
    bt.finish()
    mountains("ridge", 1500, 1700, 70, rnd, M("#8a7f86"), n=30, jag=0.25)
    return s


def brick_building(bt, x, y, w, d, h, rnd, mis, floors=None, ruined=0.0, awning=True):
    """Storefront block facing the camera.  mis = dict of material slots."""
    floors = floors or max(1, int(h / 3.4))
    if ruined > 0:
        # jagged top profile on the facade
        n = 7
        prof = [(-w / 2, 0), (w / 2, 0)]
        for i in range(n, -1, -1):
            xx = -w / 2 + w * i / n
            prof.append((xx, h - rnd.uniform(0, ruined) * h * (0.3 + 0.7 * math.sin(math.pi * i / n))))
        bt.prism(prof, y - d / 2, y + d / 2, axis="y", mi=mis["brick"], loc=(x, 0, 0))
    else:
        bt.box((w, d, h), (x, y, h / 2), mi=mis["brick"])
        bt.box((w + 0.4, d + 0.4, 0.45), (x, y, h + 0.2), mi=mis["trim"])
    face = y - d / 2
    # shopfront
    bt.box((w - 0.8, 0.14, 2.4), (x, face - 0.05, 1.5), mi=mis["dark"])
    bt.box((w - 0.4, 0.3, 0.35), (x, face - 0.12, 2.85), mi=mis["trim"])
    bt.box((w - 0.4, 0.32, 0.7), (x, face - 0.14, 3.35), mi=mis["sign"])
    if awning:
        bt.prism([(0, 3.0), (-1.6, 2.5), (-1.6, 2.4), (0, 2.85)], x - w / 2 + 0.5, x + w / 2 - 0.5,
                 axis="x", mi=mis["awning"], loc=(0, face, 0))
    for f in range(1, floors):
        z = 3.4 * f + 1.6
        if ruined > 0 and z > h * (1 - ruined * 0.6):
            break
        nw = max(2, int(w / 2.2))
        windows_row(bt, x - w / 2 + 0.5, x + w / 2 - 0.5, z, face, nw, 0.9, 1.5, mis["dark"],
                    mis["trim"], rnd, broken=0.4)
        bt.box((w, 0.2, 0.16), (x, face - 0.05, z - 1.05), mi=mis["trim"])


def scene_us_city(rnd):
    s = {}
    asphalt = ground_mat("g_asph", "#5f5d58", [(0.45, "#57554f"), (0.62, "#67645d")], patch_scale=0.25)
    ground(asphalt, None)
    walk = ground_mat("g_walk", "#8b867b", [(0.5, "#807b70")], patch_scale=0.6)
    bt = Batch("curb", [walk, M("#7a7569")], outline=0.6)
    bt.box((120, 2.6, 0.22), (0, 19.6, 0.11), mi=0)
    bt.box((120, 0.25, 0.25), (0, 18.3, 0.12), mi=1)
    bt.finish()
    line = ground_mat("g_line", "#a69a6e", patch_scale=1.0)
    for x in range(-40, 41, 6):
        strip_mesh("lane", [(x, 12.5, 0), (x + 3, 12.5, 0)], 0.18, line, z=0.015)
    cracks = ground_mat("g_crack", "#45433f", patch_scale=1.0)
    for i in range(14):
        x0, y0 = rnd.uniform(-20, 20), rnd.uniform(8, 17)
        pts = [(x0, y0, 0)]
        for k in range(5):
            pts.append((pts[-1][0] + rnd.uniform(0.4, 1.0), pts[-1][1] + rnd.uniform(-0.5, 0.5), 0))
        strip_mesh("crack", pts, 0.06, cracks, z=0.012)
    mats = [M("#8c4a36", patches=[(0.42, "#84452f"), (0.68, "#934f3a")], patch_scale=3.5),
            M("#9a5a42", patches=[(0.55, "#91533d")], patch_scale=3.5),
            M("#7b6a58"), M("#d1c6aa"), M("#22201d"), M("#6b5a47"),
            M("#6c7a6e"), M("#8f3d33"), M("#5c6670")]
    # building row (x span covers frame); gaps with rubble
    layout = [(-30, 9, 11, 0.0), (-21, 8, 9, 0.5), (-12.5, 9, 11.5, 0.0), (-4, 6, 0, 0),
              (3, 8, 10, 0.35), (11.5, 9, 12, 0.0), (20.5, 9, 9, 0.6), (29.5, 9, 13, 0.0)]
    for i, (x, w, h, ruin) in enumerate(layout):
        bt = Batch(f"bld{i}", mats)
        if h == 0:
            rubble(bt, x, 26.0, w, rnd, n=70, h=2.2, mis=(0, 1, 2, 5))
            bt.box((0.4, 6, 5.0), (x - w / 2 + 0.2, 27, 2.5), mi=0)
            bt.finish()
            continue
        mis = dict(brick=i % 2, trim=3 if i % 3 else 2, dark=4, sign=5 if i % 2 else 8,
                   awning=6 if i % 2 else 7)
        brick_building(bt, x, 27.0, w - 0.1, 10, h, rnd, mis, ruined=ruin, awning=(i % 3 != 2))
        bt.finish()
    # fire escape on bld at x=11.5 (w 9, h 15)
    bt = Batch("fire_escape", [M("#2c2b29")], outline=0.5)
    fx, face = 11.5, 27.0 - 5.0
    for f in range(1, 3):
        z = 3.4 * f + 0.6
        bt.box((4.2, 1.1, 0.1), (fx + 1.0, face - 0.6, z))
        bt.box((4.2, 0.05, 0.06), (fx + 1.0, face - 1.15, z + 0.9))
        for xx in np.linspace(fx - 1.1, fx + 3.1, 8):
            bt.box((0.04, 0.04, 0.9), (xx, face - 1.15, z + 0.45))
        if f < 2:
            bt.bar((fx - 0.8, face - 0.7, z), (fx + 2.8, face - 0.7, z + 3.4), 0.12)
    bt.finish()
    # water tower on the roof of bld x=-12.5 (h 16)
    bt = Batch("water_tower", [M("#6a5643", patches=[(0.55, "#5d4b3a")], patch_scale=2.0), M("#2f2c28"),
                               M("#4a4038")])
    tx, ty, tz = -12.5, 29.0, 11.5
    for dx, dy in ((-1.5, -1.5), (1.5, -1.5), (-1.5, 1.5), (1.5, 1.5)):
        bt.bar((tx + dx, ty + dy, tz), (tx + dx * 0.8, ty + dy * 0.8, tz + 4.0), 0.18, mi=1)
    bt.bar((tx - 1.5, ty - 1.5, tz + 0.4), (tx + 1.5, ty - 1.5, tz + 3.6), 0.08, mi=1)
    bt.bar((tx + 1.5, ty - 1.5, tz + 0.4), (tx - 1.5, ty - 1.5, tz + 3.6), 0.08, mi=1)
    bt.cone(2.2, 2.2, 3.6, (tx, ty, tz + 4.0), segs=14)
    for k in range(3):
        bt.cone(2.25, 2.25, 0.12, (tx, ty, tz + 4.6 + k * 1.1), segs=14, mi=1)
    bt.cone(2.45, 0.2, 1.4, (tx, ty, tz + 7.6), segs=14, mi=2)
    bt.finish(smooth=False)
    # rubble along the sidewalk + bent street lamps
    bt = Batch("rubble_front", [mats[0], mats[1], mats[2], mats[5]], outline=0.7)
    for x in (-24, -7, 16.5, 24):
        rubble(bt, x, 21.5, rnd.uniform(3, 5), rnd, n=35, h=1.0, mis=(0, 1, 2, 3))
    bt.finish()
    bt = Batch("lamps", [M("#2c2b29"), M("#c9b98a")], outline=0.6)
    for x, lean in ((-16, 0), (6, 12), (26, -4)):
        p0 = Vector((x, 20.6, 0))
        top = p0 + Vector((math.sin(math.radians(lean)) * 5.5, 0, math.cos(math.radians(lean)) * 5.5))
        bt.bar(p0, top, 0.14)
        arm = top + Vector((1.2, 0, 0.2))
        bt.bar(top, arm, 0.08)
        bt.box((0.5, 0.3, 0.25), arm - Vector((0, 0, 0.15)), mi=1)
    bt.finish()
    # skyline far: blocks in haze, smoke
    bt = Batch("skyline", [M("#6e6159"), M("#5e5650"), M("#7a6b60")], outline=0)
    x = -150
    while x < 150:
        w = rnd.uniform(6, 14)
        h = rnd.uniform(8, 34)
        bt.box((w, 10, h), (x, rnd.uniform(70, 130), h / 2), mi=rnd.randint(0, 2))
        if rnd.random() < 0.25:
            bt.cone(0.6, 0.6, rnd.uniform(6, 12), (x, 100, h), segs=6, mi=1)
        x += w + rnd.uniform(-2, 4)
    bt.finish()
    bt = Batch("skyline2", [M("#867a72")], outline=0)
    x = -420
    while x < 420:
        w = rnd.uniform(12, 30)
        h = rnd.uniform(20, 70)
        bt.box((w, 20, h), (x, rnd.uniform(300, 420), h / 2))
        x += w + rnd.uniform(0, 10)
    bt.finish()
    bt = Batch("smoke", [M("#4a4541"), M("#5e5853")], outline=0)
    smoke(bt, -40, 160, 55, rnd, n=11, s=3.0, drift=1.0)
    smoke(bt, 60, 220, 70, rnd, n=12, s=4.0, drift=0.8)
    bt.finish()
    return s


def hedgerow(bt, pts, rnd, bank_mi, leaf_mis, tree_mis, bank_h=1.3, bush=1.6, tree_p=0.12):
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        prof = [(-1.9, 0), (1.9, 0), (0.8, bank_h), (-0.8, bank_h)]
        bt.prism(prof, -L / 2 - 0.5, L / 2 + 0.5, axis="x", mi=bank_mi, loc=(mx, my, 0),
                 rot=(0, 0, ang))
        n = int(L / 1.1) + 1
        for i in range(n):
            t = i / max(n - 1, 1)
            x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            r = bush * rnd.uniform(0.8, 1.25)
            bt.ico(r, (x + rnd.uniform(-0.3, 0.3), y + rnd.uniform(-0.4, 0.4), bank_h + r * 0.55),
                   scale=(1.25, 1.0, rnd.uniform(0.9, 1.3)), mi=rnd.choice(leaf_mis), jitter=0.15, rnd=rnd)
            if rnd.random() < tree_p:
                tree_round(bt, x, y + 0.3, rnd.uniform(1.8, 2.6), rnd, trunk_mi=tree_mis[0],
                           leaf_mi=rnd.choice(tree_mis[1:]), blobs=3)
                bt.bm.verts.ensure_lookup_table()


def scene_eu_hedgerow(rnd):
    s = {}
    g = ground_mat("g_bocage", "#6f7a45", [(0.42, "#66733f"), (0.6, "#7a8350"), (0.72, "#717d48")],
                   patch_scale=0.03)
    ground(g, hills_fn(rnd, amp=5.5, start=50))
    lane = ground_mat("g_lane", "#8a7a5c", [(0.45, "#7c6d51"), (0.62, "#968563")], patch_scale=0.35)
    strip_mesh("lane", [(x, 12.5 + 0.6 * math.sin(x * 0.07), 0) for x in range(-40, 41, 2)], 5.6, lane)
    grass = ground_mat("g_mid", "#6d7a44", patch_scale=0.6)
    strip_mesh("lane_mid", [(x, 12.5 + 0.6 * math.sin(x * 0.07), 0) for x in range(-40, 41, 2)], 0.8,
               grass, z=0.03)
    leafs = [M("#4f6234"), M("#5a6c3a"), M("#46582f")]
    bank = M("#6e6040", patches=[(0.5, "#675a3c"), (0.66, "#67683e")], patch_scale=1.8)
    trunk = M("#4e4130")
    # near hedgerow bank behind the lane, with a gate gap
    bt = Batch("hedge_near_l", [bank, trunk] + leafs)
    hedgerow(bt, [(-45, 22.0), (-25, 22.6), (-6, 21.8)], rnd, 0, (2, 3, 4), (1, 2, 4), bush=1.1, tree_p=0.06)
    bt.finish()
    bt = Batch("hedge_near_r", [bank, trunk] + leafs)
    hedgerow(bt, [(1.5, 22.0), (12, 22.4), (17, 22.0)], rnd, 0, (2, 3, 4), (1, 2, 4), bush=1.1, tree_p=0.1)
    bt.finish()
    # gate posts & stone wall on the right
    bt = Batch("wall", [M("#8f8a7a", patches=[(0.5, "#7f7a6b"), (0.72, "#9d9787")], patch_scale=2.2),
                        M("#5d4d39"), M("#7c7a5a")])
    for x in np.arange(18, 46, 0.62):
        for row in range(3):
            bt.box((rnd.uniform(0.5, 0.75), 0.7, 0.42), (x + rnd.uniform(-0.05, 0.05) + (row % 2) * 0.3,
                   21.5, 0.22 + row * 0.42), rot=(0, rnd.uniform(-5, 5), rnd.uniform(-4, 4)))
        if rnd.random() < 0.3:
            bt.ico(0.4, (x, 21.5, 1.35), scale=(1.4, 1.0, 0.5), mi=2)
    bt.box((0.3, 0.3, 1.7), (-5.0, 21.4, 0.85), mi=1)
    bt.box((0.3, 0.3, 1.7), (0.8, 21.4, 0.85), mi=1)
    for z in (0.4, 0.8, 1.2):
        bt.box((2.8, 0.1, 0.12), (-3.4, 21.0, z), rot=(0, 0, 25), mi=1)
    bt.finish()
    # orchard behind the wall (right)
    bt = Batch("orchard", [trunk, M("#617240"), M("#6c7b45"), M("#a3423a")], outline=0.8)
    for i in range(6):
        for j in range(5):
            x = 22 + i * 4.6 + rnd.uniform(-0.4, 0.4)
            y = 28 + j * 4.8 + rnd.uniform(-0.4, 0.4)
            h = rnd.uniform(1.5, 1.9)
            bt.cone(0.14, 0.1, h, (x, y, 0), segs=6, rot=(rnd.uniform(-6, 6), rnd.uniform(-6, 6), 0))
            for k in range(3):
                bt.ico(rnd.uniform(1.1, 1.5), (x + rnd.uniform(-0.6, 0.6), y + rnd.uniform(-0.4, 0.4),
                       h + 0.7 + k * 0.3), scale=(1.2, 1.1, 0.8), mi=1 + rnd.randint(0, 1), jitter=0.15,
                       rnd=rnd)
            for k in range(4):
                bt.ico(0.12, (x + rnd.uniform(-1.1, 1.1), y - 0.9, h + rnd.uniform(0.3, 1.4)), mi=3, sub=0)
    bt.finish()
    # fields beyond: more hedgerows forming a patchwork
    bt = Batch("hedges_far", [bank, trunk] + leafs, outline=0)
    for yy in (60, 95, 140):
        pts = [(x, yy + rnd.uniform(-4, 4)) for x in range(-160, 161, 20)]
        hedgerow(bt, pts, rnd, 0, (2, 3, 4), (1, 2, 4), bank_h=1.0, bush=1.9, tree_p=0.2)
    for xx in (-55, -18, 40, 75):
        pts = [(xx + rnd.uniform(-3, 3), y) for y in range(28 if xx < 0 else 60, 141, 16)]
        hedgerow(bt, pts, rnd, 0, (2, 3, 4), (1, 2, 4), bank_h=1.0, bush=1.8, tree_p=0.2)
    bt.finish()
    # stone farmhouse midground left & far church
    stone = M("#9a917c", patches=[(0.45, "#928a75"), (0.66, "#a29a84")], patch_scale=3.0)
    bt = Batch("farmhouse", [stone, M("#5b4e48"), M("#2b2622"), M("#d8cfb7")])
    gable_house(bt, -26, 44, 11, 6.5, 5.0, 3.6, 0, 1)
    bt.box((1.8, 1.2, 9.6), (-29.5, 45.5, 4.8), mi=0)
    windows_row(bt, -31, -21, 3.4, 44 - 3.25, 3, 0.8, 1.1, 2, 3)
    bt.box((1.1, 0.12, 2.0), (-25.5, 44 - 3.3, 1.0), mi=2)
    bt.finish()
    bt = Batch("far_village", [M("#9a917c"), M("#5b4e48")], outline=0)
    gable_house(bt, 40, 210, 10, 7, 6, 4, 0, 1)
    gable_house(bt, 52, 215, 8, 7, 5, 3.5, 0, 1)
    bt.box((4, 4, 16), (46, 220, 8))
    bt.cone(2.9, 0.1, 9, (46, 220, 16), segs=4, mi=1, rot=(0, 0, 45))
    bt.finish()
    bt = Batch("trees_far", [trunk, M("#53653a"), M("#5d6d3f")], outline=0)
    for i in range(40):
        tree_round(bt, rnd.uniform(-220, 220), rnd.uniform(170, 260), rnd.uniform(3.5, 6), rnd,
                   leaf_mi=1 + i % 2)
    bt.finish()
    bt = Batch("trees_mid", [trunk, M("#53653a"), M("#5d6d3f")])
    for x, y in ((-10, 50), (8, 58), (-44, 66), (58, 70)):
        tree_round(bt, x, y, rnd.uniform(3.0, 4.0), rnd, leaf_mi=1 + rnd.randint(0, 1))
    bt.finish()
    bt = Batch("smoke", [M("#5e5a55"), M("#736d66")], outline=0)
    smoke(bt, -80, 260, 60, rnd, n=12, s=3.5, drift=0.7)
    bt.finish()
    return s


def timber_house(bt, x, y, w, d, h, rh, rnd, mi, broken=0.0, ridge="x"):
    """Half-timbered house: plaster box, dark beams, roof (maybe broken)."""
    bt.box((w, d, h), (x, y, h / 2), mi=mi["plaster"])
    face = y - d / 2
    bt.box((w + 0.3, d + 0.3, 0.9), (x, y, 0.45), mi=mi["stone"])
    for zz in (0.9, h * 0.5, h - 0.12):
        bt.box((w + 0.1, 0.16, 0.22), (x, face - 0.06, zz), mi=mi["beam"])
    n = max(2, int(w / 1.6))
    for i in range(n + 1):
        xx = x - w / 2 + w * i / n
        bt.box((0.2, 0.16, h - 0.9), (xx, face - 0.06, 0.9 + (h - 0.9) / 2), mi=mi["beam"])
        if i < n and i % 2 == 0:
            bt.bar((xx, face - 0.07, 0.95), (xx + w / n, face - 0.07, h * 0.5), 0.14, mi=mi["beam"])
    windows_row(bt, x - w / 2, x + w / 2, h * 0.73, face, max(1, n // 2), 0.8, 1.0, mi["dark"])
    # roof: front slope, optionally with a hole and exposed rafters
    if ridge == "x":
        over = 0.4
        if broken <= 0:
            bt.prism([(-d / 2 - over, 0), (d / 2 + over, 0), (0, rh)], x - w / 2 - 0.3, x + w / 2 + 0.3,
                     axis="x", mi=mi["roof"], loc=(0, y, h))
        else:
            cut = x - w / 2 + w * (0.3 + 0.4 * rnd.random())
            bt.prism([(-d / 2 - over, 0), (d / 2 + over, 0), (0, rh)], x - w / 2 - 0.3, cut - 1.2,
                     axis="x", mi=mi["roof"], loc=(0, y, h))
            bt.prism([(0, rh * 0.25), (d / 2 + over, 0), (0, rh)], cut + 1.6, x + w / 2 + 0.3,
                     axis="x", mi=mi["roof"], loc=(0, y, h))
            for xx in np.arange(cut - 1.0, cut + 1.6, 0.6):
                bt.bar((xx, y - d / 2, h), (xx, y, h + rh * rnd.uniform(0.6, 1.0)), 0.14, mi=mi["beam"])
            bt.box((w * 0.2, 0.3, rh * 0.8), (x - w / 2 + 0.2 + w * 0.1, y, h + rh * 0.4),
                   mi=mi["plaster"])
    bt.box((0.9, 0.9, 2.0), (x + w * 0.3, y + d * 0.1, h + rh * 0.6), mi=mi["stone"])


def scene_eu_village(rnd):
    s = {}
    cob = ground_mat("g_cobble", "#857c6c", [(0.45, "#7a7262"), (0.6, "#8f8574"), (0.75, "#7f7766")],
                     patch_scale=0.5)
    g = ground_mat("g_vgrass", "#6f7449", [(0.5, "#666b42")], patch_scale=0.05)
    ground(g, hills_fn(rnd, amp=6, start=70))
    bt = Batch("square", [cob], outline=0)
    bt.box((90, 40, 0.04), (0, 22, 0.0))
    bt.finish(recalc=False)
    mi_mats = [M("#d9ceb2", patches=[(0.62, "#d0c4a8")], patch_scale=2.0), M("#3e2f24"),
               M("#8a4b38", patches=[(0.55, "#804535")], patch_scale=3.0), M("#8a8170"),
               M("#211e1b"), M("#c8b998")]
    mi = dict(plaster=0, beam=1, roof=2, stone=3, dark=4)
    houses = [(-27, 32, 8, 7, 7.5, 4.2, 0.0), (-18.5, 33, 7, 7, 6.5, 3.8, 1.0),
              (-10.5, 34, 7, 7, 8.0, 4.0, 0.0), (15, 33, 8, 7, 7.0, 4.0, 1.0), (24, 32, 8.5, 7, 8.5, 4.4, 0.0),
              (33, 33, 7, 7, 6.5, 3.8, 1.0)]
    for i, (x, y, w, d, h, rh, br) in enumerate(houses):
        bt = Batch(f"house{i}", mi_mats)
        timber_house(bt, x, y, w, d, h, rh, rnd, mi, broken=br)
        bt.finish()
    # ruin: a gutted house shell with rubble
    bt = Batch("ruin", mi_mats)
    prof = [(-4, 0), (4, 0), (4, 3.2), (2.5, 5.5), (1.0, 4.0), (-0.5, 6.5), (-2.5, 4.2), (-4, 4.8)]
    bt.prism(prof, 30.0, 30.6, axis="y", mi=0, loc=(-36, 0, 0))
    bt.box((4.0, 0.14, 1.4), (-36, 29.94, 2.4), mi=4)
    rubble(bt, -36, 27.0, 6, rnd, n=60, h=1.6, mis=(0, 2, 3))
    bt.finish()
    # church with broken steeple
    stone = M("#9b927f", patches=[(0.45, "#938a76"), (0.66, "#a39b87")], patch_scale=2.6)
    bt = Batch("church", [stone, M("#5d5650"), M("#211e1b"), M("#7c7466")])
    cx, cy = 3.0, 52.0
    bt.box((9, 18, 10), (cx + 6, cy + 6, 5))
    bt.prism([(-4.9, 0), (4.9, 0), (0, 5.0)], cy - 3, cy + 15, axis="y", mi=1, loc=(cx + 6, 0, 10))
    bt.box((6, 6, 15), (cx - 2, cy, 7.5))
    bt.box((6.6, 6.6, 0.6), (cx - 2, cy, 15.2), mi=3)
    # broken spire: jagged stub
    prof = [(-2.8, 0), (2.8, 0), (2.0, 3.0), (1.2, 5.4), (0.4, 3.6), (-0.8, 6.8), (-1.6, 4.0), (-2.4, 2.2)]
    bt.prism(prof, cy - 2.8, cy + 2.8, axis="y", mi=0, loc=(cx - 2, 0, 15.5))
    for z in (7.0, 12.0):
        bt.box((1.2, 0.15, 2.4), (cx - 2, cy - 3.05, z), mi=2)
    bt.prism([(-0.8, 0), (0.8, 0), (0.8, 2.0), (0, 2.8), (-0.8, 2.0)], cy - 3.08, cy - 3.0, axis="y",
             mi=2, loc=(cx - 2, 0, 3.0))
    for i in range(3):
        bt.prism([(-0.6, 0), (0.6, 0), (0.6, 2.2), (0, 3.0), (-0.6, 2.2)], cy - 3.08, cy - 3.0,
                 axis="y", mi=2, loc=(cx + 3.5 + i * 2.5, 0, 3.0))
    rubble(bt, cx - 2, cy - 4.5, 6, rnd, n=40, h=1.4, mis=(0, 3))
    bt.finish()
    # fountain (behind the strip, left of centre)
    bt = Batch("fountain", [M("#a39a86"), M("#8d8572"), M("#3c5a5c")])
    fx, fy = -4.0, 23.5
    bt.cone(2.6, 2.6, 0.8, (fx, fy, 0), segs=12)
    bt.cone(2.25, 2.25, 0.05, (fx, fy, 0.76), segs=12, mi=2)
    bt.cone(0.35, 0.3, 2.2, (fx, fy, 0.8), segs=8, mi=1)
    bt.cone(0.9, 1.2, 0.35, (fx, fy, 2.6), segs=10)
    bt.cone(0.25, 0.1, 0.9, (fx, fy, 2.95), segs=8, mi=1)
    bt.finish()
    # sandbags & cart wreck-free rubble near houses
    bt = Batch("rubble_front", mi_mats, outline=0.7)
    for x in (-22, 9, 19):
        rubble(bt, x, 26.5, rnd.uniform(3, 5), rnd, n=30, h=1.0, mis=(0, 2, 3))
    bt.finish()
    bt = Batch("trees", [M("#4e4130"), M("#5a6a3c"), M("#4f5f36")], outline=0.6)
    for x, y in ((-46, 40), (44, 42), (12, 75), (-14, 80)):
        tree_round(bt, x, y, rnd.uniform(2.8, 3.6), rnd, leaf_mi=1 + rnd.randint(0, 1))
    bt.finish()
    bt = Batch("trees_far", [M("#4e4130"), M("#56653a"), M("#5f6c40")], outline=0)
    for i in range(40):
        tree_round(bt, rnd.uniform(-220, 220), rnd.uniform(150, 260), rnd.uniform(3.5, 6), rnd,
                   leaf_mi=1 + i % 2)
    bt.finish()
    bt = Batch("roofs_far", [M("#b9ab90"), M("#7a4a3a")], outline=0)
    for i in range(14):
        gable_house(bt, rnd.uniform(-120, 120), rnd.uniform(110, 160), rnd.uniform(6, 10), 6,
                    rnd.uniform(4, 6), 3.5, 0, 1)
    bt.finish()
    bt = Batch("smoke", [M("#4f4a46"), M("#655e58")], outline=0)
    smoke(bt, 20, 70, 32, rnd, n=11, s=1.8, drift=1.0)
    smoke(bt, -70, 220, 60, rnd, n=12, s=3.5, drift=0.8)
    bt.finish()
    return s


def scene_asia_jungle(rnd):
    s = {}
    g = ground_mat("g_jungle", "#5d6a3a", [(0.45, "#55623a"), (0.6, "#66703f")], patch_scale=0.04)
    ground(g, hills_fn(rnd, amp=9, start=60, scale=0.7))
    path = ground_mat("g_mud", "#7b6a4c", [(0.45, "#6f5f43"), (0.62, "#857352")], patch_scale=0.4)
    strip_mesh("path", [(x, 12.5 + 0.8 * math.sin(x * 0.06 + 1), 0) for x in range(-40, 41, 2)], 6.5, path)
    trunk = M("#5a4a3a")
    leafs = [M("#46613a"), M("#527040"), M("#3e5634"), M("#5d7a45")]
    bamboo = M("#8a9a52", patches=[(0.6, "#7a8a48")], patch_scale=2.0)
    # ferns along the path edge (low)
    bt = Batch("ferns", leafs, outline=0.45)
    for i in range(30):
        x, y = rnd.uniform(-32, 32), rnd.uniform(19.5, 21.5)
        shrub(bt, x, y, rnd.uniform(0.7, 1.1), rnd, mi=rnd.randint(0, 3), n=3)
    bt.finish()
    # bamboo groves left and right
    for nm, cx, cy in (("bamboo_l", -20, 26), ("bamboo_l2", -30, 30), ("bamboo_r", 18, 27), ("bamboo_r2", 29, 25)):
        bt = Batch(nm, [bamboo, leafs[1], leafs[3]], outline=0.6)
        bamboo_clump(bt, cx, cy, 1.0, rnd, cane_mi=0, leaf_mi=rnd.choice((1, 2)), n=14)
        bt.finish()
    # broadleaf trees & palms
    bt = Batch("jungle_mid", [trunk] + leafs, outline=0.7)
    for x, y in ((-38, 36), (-10, 40), (10, 44), (38, 34), (-28, 48), (26, 50)):
        tree_round(bt, x, y, rnd.uniform(3.0, 4.2), rnd, leaf_mi=1 + rnd.randint(0, 3), blobs=4)
    for x, y in ((-14, 30), (7, 31), (-44, 28), (44, 29)):
        palm(bt, x, y, 1.0, rnd, trunk_mi=0, leaf_mi=1 + rnd.randint(0, 3))
    bt.finish()
    # mossy stone temple ruin (centre)
    stone = M("#8d8a74", patches=[(0.5, "#858269"), (0.64, "#6f7a52")], patch_scale=1.6)
    dark = M("#25261f")
    bt = Batch("temple", [stone, dark, M("#9a967f"), leafs[0]])
    tx, ty = -1.0, 46.0
    for k, (w, h) in enumerate(((16, 1.6), (13, 1.5), (10, 1.5))):
        z = sum(hh for _, hh in ((16, 1.6), (13, 1.5), (10, 1.5))[:k])
        bt.box((w, w * 0.8, h), (tx, ty, z + h / 2))
    bt.box((4.0, 0.2, 2.4), (tx, ty - 6.5, 1.2), mi=1)
    for k in range(5):
        bt.box((5.0, 0.8, 0.35), (tx, ty - 7.0 - k * 0.6, 4.5 - k * 0.9 - 0.2), mi=2)
    # tower: stepped body, broken top
    z = 4.6
    for w, h in ((7, 3.0), (6, 2.6), (5, 2.2)):
        bt.box((w, w, h), (tx, ty, z + h / 2))
        bt.box((w + 0.5, w + 0.5, 0.35), (tx, ty, z + h), mi=2)
        z += h + 0.35
    bt.box((1.4, 0.2, 2.2), (tx, ty - 3.55, 6.0), mi=1)
    prof = [(-2.0, 0), (2.0, 0), (1.6, 2.2), (0.9, 3.6), (0.3, 2.8), (-0.6, 4.4), (-1.5, 2.4)]
    bt.prism(prof, ty - 2.0, ty + 2.0, axis="y", mi=0, loc=(tx, 0, z))
    # side shrine stupa
    bt.cone(1.8, 1.8, 2.0, (tx + 11, ty + 2, 0), segs=10)
    bt.cone(1.6, 0.2, 3.5, (tx + 11, ty + 2, 2.0), segs=10, mi=0)
    rubble(bt, tx - 9, ty - 3, 4, rnd, n=25, h=1.2, mis=(0, 2))
    # vines/moss lumps
    for i in range(16):
        bt.ico(rnd.uniform(0.6, 1.2), (tx + rnd.uniform(-7, 7), ty - rnd.uniform(3.5, 6.5), rnd.uniform(0.5, 5)),
               scale=(1.3, 0.6, 0.8), mi=3, jitter=0.2, rnd=rnd)
    bt.finish()
    # canopy wall behind
    bt = Batch("canopy_far", [trunk] + leafs, outline=0)
    for i in range(90):
        tree_round(bt, rnd.uniform(-160, 160), rnd.uniform(62, 120), rnd.uniform(4, 7), rnd,
                   leaf_mi=1 + rnd.randint(0, 3), blobs=3)
    bt.finish()
    # rice terraces on a far hillside + karst peaks
    terr = [M("#7f9a62"), M("#9bb07a"), M("#6f8a58"), M("#a8b98a")]
    bt = Batch("terraces", terr, outline=0)
    hx, hy = 70, 330
    for k in range(14):
        r = 120 - k * 7.5
        bt.cone(r, r, 3.2, (hx, hy, k * 3.2), segs=22, mi=k % 4, scale=(1.0, 0.55, 1))
    for k in range(10):
        r = 90 - k * 7
        bt.cone(r, r, 3.0, (-120, 380, k * 3.0), segs=20, mi=(k + 1) % 4, scale=(1.0, 0.5, 1))
    bt.finish()
    karst = M("#5f7462")
    bt = Batch("karst", [karst, M("#6b8070")], outline=0)
    for i in range(18):
        x = rnd.uniform(-700, 700)
        y = rnd.uniform(650, 1000)
        h = rnd.uniform(90, 200)
        bt.cone(h * 0.32, h * 0.12, h, (x, y, -5), segs=9, mi=i % 2)
        bt.ico(h * 0.16, (x, y, h - 5), scale=(1, 1, 0.8), mi=i % 2)
    bt.finish()
    return s


def scene_asia_snow(rnd):
    s = {}
    g = ground_mat("g_snow", "#e3e8ea", [(0.45, "#d6dde2"), (0.62, "#eaeef0")], patch_scale=0.05,
                   shadow=0.74)
    ground(g, hills_fn(rnd, amp=5, start=170))
    track = ground_mat("g_track", "#c8d0d6", [(0.5, "#bcc5cc")], patch_scale=0.6, shadow=0.74)
    for off in (-0.9, 0.9):
        strip_mesh("track", [(x, 12.5 + off + 0.3 * math.sin(x * 0.04), 0) for x in range(-40, 41, 2)],
                   0.55, track, z=0.02)
    # frozen river winding from the distance to the right midground
    ice = ground_mat("g_ice", "#86aebf", [(0.42, "#7aa3b6"), (0.6, "#9bbfcd"), (0.75, "#b4d2dc")],
                     patch_scale=0.3, shadow=0.8)
    pts = []
    for i in range(60):
        t = i / 59
        y = 22 + t ** 1.6 * 700
        x = 30 - 55 * math.sin(t * 4.0) * (1 - t * 0.6) + t * 40
        pts.append((x, y, 0))
    strip_mesh("river", pts, lambda i: 13 + i * 0.9, ice, z=0.04)
    bank = Batch("riverbank", [toon_snow("#d3dbe0", thr=0.2)], outline=0)
    for (x, y, _), w in zip(pts[:40], [13 + i * 0.9 for i in range(40)]):
        for side in (-1, 1):
            bmesh.ops.create_uvsphere(bank.bm, u_segments=12, v_segments=6, radius=1.0 + w * 0.08,
                                      matrix=Batch._mat((x + side * (w / 2 + 0.3), y, -0.3), None,
                                                        (1.8, 1.6, 0.4)))
    bank.finish(smooth=True)
    # snow drifts (low mounds) behind the strip
    bt = Batch("drifts", [toon_snow("#dfe6ea", thr=0.2)], outline=0)
    for i in range(10):
        x = rnd.choice((-1, 1)) * rnd.uniform(14, 34)
        bmesh.ops.create_uvsphere(bt.bm, u_segments=14, v_segments=7, radius=rnd.uniform(1.4, 2.4),
                                  matrix=Batch._mat((x, rnd.uniform(20.5, 26), -0.5), (0, 0, rnd.uniform(-20, 20)),
                                                    (2.0, 1.2, 0.5)))
    bt.finish(smooth=True)
    # pine forest, left and right groups leaving the river view open
    trunk = M("#4b3d30")
    needles = [toon_snow("#2f4a3c", thr=0.38), toon_snow("#36513f", thr=0.4),
               toon_snow("#2b4236", thr=0.36)]
    for nm, rng_x, rng_y, cnt, sc_, ol in (("pines_l", (-45, -6), (24, 46), 22, (1.6, 2.4), 0.7),
                                         ("pines_r", (16, 48), (24, 46), 18, (1.6, 2.4), 0.7),
                                         ("pines_mid", (-120, 120), (60, 130), 80, (2.0, 3.0), 0.0),
                                         ("pines_far", (-300, 300), (160, 300), 140, (3.0, 4.2), 0.0)):
        bt = Batch(nm, [trunk] + needles, outline=ol)
        for i in range(cnt):
            x, y = rnd.uniform(*rng_x), rnd.uniform(*rng_y)
            # keep a corridor open over the river
            if True:
                tt = max(0.0, (y - 32) / 700) ** (1 / 1.6)
                rx = 30 - 55 * math.sin(tt * 4.0) * (1 - tt * 0.6) + tt * 40
                if abs(x - rx) < 12 + y * 0.03:
                    continue
            pine(bt, x, y, rnd.uniform(*sc_), rnd, leaf_mi=1 + rnd.randint(0, 2))
        bt.finish()
    # broken log fence / posts near drifts
    bt = Batch("posts", [toon_snow("#5a4a3a")], outline=0.6)
    for x in (-24, -21, -18, 22, 25):
        bt.box((0.2, 0.2, 1.4), (x, 22.0, 0.5), rot=(rnd.uniform(-8, 8), rnd.uniform(-10, 10), 0))
    bt.finish()
    # distant mountains with snow caps
    mm = zband_mat("mtn_snow", [(0, "#6e7b8a"), (90, "#8592a0"), (150, "#d9e0e6"), (260, "#eef2f5")])
    mountains("mtn1", 1300, 1800, 260, rnd, mm, n=28, jag=0.35)
    mm2 = zband_mat("mtn_snow2", [(0, "#7d8a98"), (120, "#97a3b0"), (200, "#dde3e8"), (400, "#eef2f5")])
    mountains("mtn2", 2300, 2600, 420, rnd, mm2, n=24, jag=0.3)
    return s


BACKDROPS = {
    "us_farm": dict(build=scene_us_farm, seed=3,
                    sky=[(0.0, "#3d4a66"), (0.3, "#7a6a7a"), (0.5, "#c98d6a"), (0.62, "#e3b07c")],
                    sun=(0.16, 0.5, 0.45, "#f2c48a", 0.65),
                    clouds=[(0.06, 0.26, 6, 0.26, (128, 104, 122), (226, 160, 128), 0.9),
                            (0.26, 0.42, 6, 0.18, (170, 124, 120), (242, 190, 140), 0.8)],
                    haze=("#d9a77d", 25, 1200, 0.92, 0.55), key=(-0.75, -0.35, 0.42),
                    tint=("#f0b080", 0.12)),
    "us_city": dict(build=scene_us_city, seed=5, push=(19.5, 34.0),
                    sky=[(0.0, "#4a4b50"), (0.35, "#77706a"), (0.6, "#a58f78")],
                    sun=(0.2, 0.46, 0.4, "#c79b72", 0.4),
                    clouds=[(0.05, 0.3, 9, 0.24, (84, 80, 80), (140, 128, 118), 0.85),
                            (0.25, 0.45, 7, 0.18, (110, 100, 94), (170, 150, 128), 0.7)],
                    haze=("#a08d7a", 30, 500, 0.9, 0.6), key=(-0.6, -0.45, 0.6), tint=("#d8b090", 0.08)),
    "eu_hedgerow": dict(build=scene_eu_hedgerow, seed=7, push=(19.0, 16.0),
                        sky=[(0.0, "#59646c"), (0.35, "#8a9192"), (0.6, "#b5b3a3")],
                        clouds=[(0.04, 0.28, 9, 0.24, (98, 106, 112), (160, 164, 160), 0.85),
                                (0.24, 0.44, 7, 0.18, (130, 134, 132), (186, 184, 170), 0.65)],
                        haze=("#a9ab9e", 25, 700, 0.9, 0.6), key=(-0.6, -0.45, 0.62)),
    "eu_village": dict(build=scene_eu_village, seed=9, push=(19.0, 21.0),
                       sky=[(0.0, "#3b3f55"), (0.32, "#6f6575"), (0.52, "#b0826a"), (0.62, "#cf9a72")],
                       sun=(0.82, 0.52, 0.35, "#e3a878", 0.5),
                       clouds=[(0.05, 0.3, 8, 0.23, (86, 80, 96), (190, 132, 110), 0.85),
                               (0.28, 0.45, 6, 0.16, (120, 100, 104), (215, 160, 122), 0.7)],
                       haze=("#b8917a", 30, 800, 0.9, 0.6), key=(0.7, -0.4, 0.5), tint=("#e0a080", 0.08)),
    "asia_jungle": dict(build=scene_asia_jungle, seed=11, push=(22.0, 16.0),
                        sky=[(0.0, "#58706a"), (0.35, "#93a497"), (0.6, "#c3c9b4")],
                        clouds=[(0.06, 0.3, 7, 0.24, (120, 138, 128), (190, 200, 184), 0.6)],
                        haze=("#b4beab", 18, 650, 0.93, 0.5), key=(-0.55, -0.45, 0.65),
                        mist=(0.4, 0.62, "#c8cebb", 0.32)),
    "asia_snow": dict(build=scene_asia_snow, seed=13, push=(19.0, 12.0),
                      sky=[(0.0, "#4d5a6e"), (0.35, "#8492a3"), (0.6, "#bcc6cf")],
                      clouds=[(0.04, 0.3, 9, 0.24, (98, 110, 128), (170, 180, 192), 0.8)],
                      haze=("#b9c3cc", 25, 1600, 0.9, 0.55), key=(-0.6, -0.4, 0.62), snowy=True,
                      snowfall=True, tint=("#c0d0e0", 0.06)),
}


def snowfall(img, seed, n=900):
    W, H = img.size
    layer = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(layer)
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.uniform(0, W), rnd.uniform(0, H)
        r = rnd.choice((0.9, 1.2, 1.6, 2.2))
        d.ellipse((x - r, y - r, x + r, y + r), fill=int(rnd.uniform(110, 220)))
    layer = layer.filter(ImageFilter.GaussianBlur(0.6))
    white = Image.new("RGB", (W, H), (242, 246, 250))
    return Image.composite(white, img, layer)


def mist_band(img, y0, y1, hx, amt):
    W, H = img.size
    a = np.asarray(img, np.float32)
    ys = np.arange(H, dtype=np.float32) / H
    c = (y0 + y1) / 2
    w = (y1 - y0) / 2
    m = np.clip(1 - np.abs(ys - c) / w, 0, 1) ** 1.5 * amt
    rng = np.random.default_rng(3)
    n = vnoise(H, W, 6, 5, octaves=3)
    m = m[:, None] * (0.6 + 0.8 * n)
    a = a + (np.array(hex_rgb(hx), np.float32) - a) * np.clip(m, 0, 1)[..., None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def setup_backdrop_ctx(cfg):
    Ctx.haze = cfg["haze"]
    Ctx.key = Vector(cfg["key"]).normalized()
    Ctx.bands = BANDS
    Ctx.snowy = cfg.get("snowy", False)
    Ctx.outline_k = cfg.get("outline_k", 0.0016)
    Ctx.outline_far = cfg.get("outline_far", 110.0)
    Ctx.push = cfg.get("push")


def render_backdrop(name):
    if name == "base":
        return render_base()
    t0 = time.time()
    cfg = BACKDROPS[name]
    sc = reset_scene(samples=cfg.get("samples", 16))
    Cam.h, Cam.pitch, Cam.lens, Cam.x = cfg.get("cam", (2.8, 3.2, 38.0, 0.0))
    setup_backdrop_ctx(cfg)
    cam = bd_camera(sc)
    rnd = random.Random(cfg["seed"])
    cfg["build"](rnd)
    sun_for(cfg["key"], 0.62)
    raw = render_raw(sc, name)
    fg = Image.open(raw).convert("RGBA")
    sky = paint_sky(cfg, cfg["seed"]).convert("RGBA")
    img = Image.alpha_composite(sky, fg).convert("RGB")
    if cfg.get("mist"):
        img = mist_band(img, *cfg["mist"])
    if cfg.get("snowfall"):
        img = snowfall(img, cfg["seed"])
    img = bloom(img, thr=0.86, radius=14, amount=0.35)
    img = grade(img, cfg)
    path = os.path.join(BG_DIR, f"{name}.jpg")
    size = save_jpeg(img, path, 82, 350)
    _, y_at = frame_geom()
    print(f"[bg] {name}: {size // 1024} KB, strip y {y_at(1.0):.1f}..{y_at(1 - STRIP):.1f} m "
          f"({time.time() - t0:.1f}s)", flush=True)
    return {"file": f"{name}.jpg", "w": BG_W, "h": BG_H}


NIGHT = "#18213a"


def N(hx, t=0.42):
    """Night version of a day colour (moonlit, desaturated toward navy)."""
    return mix_hex(hx, NIGHT, t)


def tent(bt, x, y, w, d, h, mi_canvas, mi_dark, mi_pole, open_front=True):
    """Ridge tent, ridge along x, entrance facing the camera (-y)."""
    prof = [(-d / 2, 0), (d / 2, 0), (d / 2 - 0.2, 0.6), (0, h), (-d / 2 + 0.2, 0.6)]
    bt.prism(prof, x - w / 2, x + w / 2, axis="x", mi=mi_canvas, loc=(0, y, 0))
    # end flap / dark entrance on the long front face
    if open_front:
        bt.prism([(-0.9, 0), (0.9, 0), (0, h * 0.78)], y - d / 2 - 0.04, y - d / 2 + 0.05, axis="y",
                 mi=mi_dark, loc=(x, 0, 0))
    for xx in (x - w / 2 - 0.1, x + w / 2 + 0.1):
        bt.box((0.12, 0.12, h + 0.3), (xx, y, (h + 0.3) / 2), mi=mi_pole)
    bt.box((w + 0.5, 0.1, 0.1), (x, y, h + 0.02), mi=mi_pole)
    for sx in (-1, 1):
        for xx in (x - w / 2 - 0.1, x + w / 2 + 0.1):
            bt.bar((xx, y, h + 0.2), (xx + sx * 0.0, y + sx * (d / 2 + 1.2), 0.0), 0.04, mi=mi_pole)


def sandbag_row(bt, pts, rnd, mis, rows=2):
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
        n = max(1, int(L / 0.78))
        for r in range(rows):
            for i in range(n):
                t = (i + 0.5 * (r % 2) + 0.25) / n
                if t > 1:
                    continue
                x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                bmesh.ops.create_uvsphere(
                    bt.bm, u_segments=10, v_segments=5, radius=0.5,
                    matrix=Batch._mat((x, y, 0.22 + r * 0.38), (0, 0, ang + rnd.uniform(-6, 6)),
                                      (0.82, 0.52, 0.42)))
                for f in bt.bm.faces[-40:] if False else ():
                    pass


def jeep(bt, x, y, mis, yaw=0.0):
    """Small fictional field car, low poly.  mis: body, dark, tyre, glass."""
    T = Matrix.Translation((x, y, 0)) @ Matrix.Rotation(math.radians(yaw), 4, "Z")

    def b(size, loc, mi, rot=None):
        p = T @ Vector(loc)
        r = (0, 0, yaw) if rot is None else (rot[0], rot[1], rot[2] + yaw)
        bt.box(size, tuple(p), rot=r, mi=mi)
    b((3.4, 1.7, 0.7), (0, 0, 0.85), mis[0])
    b((1.3, 1.6, 0.35), (1.15, 0, 1.33), mis[0])
    b((0.1, 1.6, 0.75), (0.45, 0, 1.55), mis[1], rot=(0, -12, 0))
    b((0.06, 1.4, 0.55), (0.42, 0, 1.55), mis[3], rot=(0, -12, 0))
    b((1.4, 1.5, 0.18), (-0.7, 0, 1.25), mis[1])
    b((0.3, 1.9, 0.18), (1.8, 0, 0.6), mis[1])
    for wx in (-1.1, 1.1):
        for wy in (-0.88, 0.88):
            p = T @ Vector((wx, wy, 0.45))
            bt.cone(0.45, 0.45, 0.32, tuple(p), rot=(90, 0, yaw), segs=12, base=False, mi=mis[2])
    p = T @ Vector((-1.85, 0, 1.0))
    bt.cone(0.42, 0.42, 0.25, tuple(p), rot=(0, 90, yaw), segs=12, base=False, mi=mis[2])


def lantern_post(bt, x, y, h, mi_pole, mi_glow):
    bt.box((0.12, 0.12, h), (x, y, h / 2), mi=mi_pole)
    bt.box((0.7, 0.08, 0.08), (x + 0.3, y, h - 0.1), mi=mi_pole)
    bt.box((0.24, 0.24, 0.32), (x + 0.6, y, h - 0.42), mi=mi_glow)
    bt.box((0.3, 0.3, 0.06), (x + 0.6, y, h - 0.24), mi=mi_pole)


BASE = dict(seed=21, cam=(6.2, 7.5, 29.0, 0.0),
            sky=[(0.0, "#0a0f1e"), (0.35, "#151d35"), (0.55, "#26304d")],
            stars=True, sun=(0.78, 0.13, 0.12, "#a9b8d8", 0.5),
            clouds=[(0.06, 0.24, 5, 0.22, (22, 30, 52), (70, 84, 118), 0.75)],
            haze=("#1c2440", 30, 450, 0.85, 0.7), key=(-0.45, -0.5, 0.74), vignette=0.32)

WARM = "#ffb661"


def render_base():
    t0 = time.time()
    cfg = BASE
    sc = reset_scene(samples=20)
    Cam.h, Cam.pitch, Cam.lens, Cam.x = cfg["cam"]
    setup_backdrop_ctx(cfg)
    Ctx.outline_far = 140.0
    Ctx.outline_k = 0.0014
    cam = bd_camera(sc)
    rnd = random.Random(cfg["seed"])
    # lantern / glow light pools (computed in every toon shader)
    lamps = [((-8.5, 29.5, 2.2), WARM, 7.5, 1.35), ((7.4, 28.5, 2.2), WARM, 7.5, 1.35),
             ((-6.0, 40.0, 2.3), WARM, 6.5, 1.3), ((7.0, 44.2, 2.6), WARM, 7.0, 1.2),
             ((0.5, 26.6, 1.2), MINT, 5.0, 1.4), ((13.0, 31.5, 1.6), WARM, 5.0, 1.1),
             ((-5.0, 19.5, 2.0), WARM, 4.5, 0.9)]
    Ctx.lights = [(Vector(p), c, r, st) for p, c, r, st in lamps]
    glow_w = M(WARM, emissive=True)
    glow_m = M(MINT, emissive=True)
    win = M("#ffc77a", emissive=True)
    pole = M(N("#4a3c2e"))
    stations = {}

    g = ground_mat("g_base", N("#5f6640", 0.5), [(0.42, N("#565c3a", 0.5)), (0.6, N("#6b6a48", 0.5)),
                                                  (0.74, N("#736650", 0.5))], patch_scale=0.06)
    ground(g, hills_fn(rnd, amp=2.5, start=90))
    yard = ground_mat("g_yard", N("#7a6a52", 0.5), [(0.45, N("#6d5f49", 0.5)), (0.62, N("#857560", 0.5))],
                      patch_scale=0.35)
    bt = Batch("yard", [yard], outline=0)
    bmesh.ops.create_circle(bt.bm, cap_ends=True, segments=40, radius=1.0,
                            matrix=Batch._mat((0.5, 34.0, 0.03), None, (17.0, 11.0, 1)))
    bt.finish(recalc=False)

    # Command post: stone farmhouse
    stone = M(N("#9a917c"), patches=[(0.45, N("#928a75")), (0.66, N("#a39b86"))], patch_scale=2.6)
    bt = Batch("farmhouse", [stone, M(N("#5c4f4a")), M(N("#2a2420")), win, M(N("#6b5a44"))])
    hx, hy, hw, hd, hh, rh = -6.0, 45.0, 10.0, 7.0, 5.0, 3.4
    gable_house(bt, hx, hy, hw, hd, hh, rh, 0, 1)
    bt.box((1.2, 1.2, 2.2), (hx + 2.6, hy + 1.0, hh + rh - 0.6), mi=0)
    f = hy - hd / 2
    for wx in (-3.4, -1.2, 2.6):
        bt.box((0.9, 0.12, 1.0), (hx + wx, f - 0.04, 3.6), mi=3)
        bt.box((1.1, 0.16, 0.12), (hx + wx, f - 0.06, 3.05), mi=4)
    for wx in (-3.4, 2.6):
        bt.box((0.9, 0.12, 1.0), (hx + wx, f - 0.04, 1.6), mi=3)
    bt.box((1.2, 0.12, 2.1), (hx + 0.7, f - 0.04, 1.05), mi=3)
    bt.box((1.5, 0.18, 0.16), (hx + 0.7, f - 0.08, 2.15), mi=4)
    bt.finish()
    stations["command"] = (hx, hy, hh + rh + 0.4)
    bt = Batch("lamp_cp", [pole, glow_w])
    bt.box((0.08, 0.6, 0.08), (hx + 1.6, f - 0.3, 2.6), mi=0)
    bt.box((0.24, 0.24, 0.32), (hx + 1.6, f - 0.62, 2.35), mi=1)
    bt.finish()

    # Barracks: barn
    bt = Batch("barn", [M(N("#7d3a2e"), patches=[(0.55, N("#743528"))], patch_scale=1.5), M(N("#4a4845")),
                        M(N("#cfc3a8")), M("#e8a65a", emissive=True), M(N("#2a1d17"))])
    bx, by, bw, bd, bh = 9.5, 49.0, 11.0, 9.0, 4.6
    bt.box((bw, bd, bh), (bx, by, bh / 2))
    prof = [(-bd / 2 - 0.4, 0), (bd / 2 + 0.4, 0), (bd / 2 - 0.5, 2.1), (0.9, 3.8), (-0.9, 3.8),
            (-bd / 2 + 0.5, 2.1)]
    bt.prism(prof, bx - bw / 2 - 0.3, bx + bw / 2 + 0.3, axis="x", mi=1, loc=(0, by, bh))
    f = by - bd / 2
    bt.box((3.4, 0.2, 3.4), (bx, f - 0.05, 1.7), mi=3)
    bt.box((1.4, 0.24, 3.5), (bx + 2.4, f - 0.25, 1.75), rot=(0, 0, -35), mi=4)
    for xo in (-1.7, 1.7):
        bt.box((0.2, 0.26, 3.5), (bx + xo, f - 0.08, 1.75), mi=2)
    bt.box((3.6, 0.26, 0.2), (bx, f - 0.08, 3.5), mi=2)
    bt.box((1.4, 0.2, 1.0), (bx, f - 0.05, 6.0), mi=3)
    windows_row(bt, bx - bw / 2 + 0.5, bx - 2.2, 2.6, f, 1, 0.8, 0.8, 3, 2)
    windows_row(bt, bx + 2.2, bx + bw / 2 - 0.5, 2.6, f, 1, 0.8, 0.8, 3, 2)
    bt.finish()
    stations["barracks"] = (bx, by, bh + 3.8 + 0.4)

    # Quartermaster tent + weapon racks (left)
    canvas = M(N("#7b7a52"), patches=[(0.6, N("#76754d"))], patch_scale=3.5)
    bt = Batch("qm_tent", [canvas, M("#3a2a1a"), pole, M(N("#3b3a33")), M(N("#5e4a34"))])
    qx, qy = -9.5, 31.5
    tent(bt, qx, qy, 6.0, 4.4, 3.0, 0, 1, 2)
    for rx in (qx - 2.2, qx + 2.0):
        ry = qy - 3.4
        bt.box((1.9, 0.12, 0.12), (rx, ry, 1.15), mi=4)
        for sx in (-0.9, 0.9):
            bt.bar((rx + sx, ry - 0.35, 0), (rx + sx, ry, 1.25), 0.1, mi=4)
            bt.bar((rx + sx, ry + 0.35, 0), (rx + sx, ry, 1.25), 0.1, mi=4)
        for k in range(5):
            xx = rx - 0.7 + k * 0.35
            bt.bar((xx, ry - 0.45, 0.02), (xx + 0.05, ry - 0.02, 1.4), 0.07, mi=3)
            bt.box((0.12, 0.1, 0.3), (xx + 0.01, ry - 0.42, 0.18), mi=4, rot=(20, 0, 0))
    # crates & barrels by the tent
    for cx_, cy_, s_ in ((qx + 3.6, qy - 1.0, 0.9), (qx + 3.9, qy + 0.2, 0.8), (qx + 3.7, qy - 0.4, 0.6)):
        bt.box((s_, s_, s_), (cx_, cy_, s_ / 2 + (0.85 if s_ < 0.7 else 0)), mi=4,
               rot=(0, 0, rnd.uniform(-15, 15)))
    bt.finish()
    stations["armory"] = (qx, qy, 3.0 + 0.4)
    bt = Batch("lamp_qm", [pole, glow_w])
    lantern_post(bt, qx + 0.6, qy - 2.6, 2.6, 0, 1)
    bt.finish()

    # Radio tent + antenna (right)
    bt = Batch("radio_tent", [canvas, M("#2a2016"), pole, M(N("#3e4a3c")), M(N("#5e4a34")),
                              M("#ffcf7a", emissive=True)])
    rx, ry = 11.0, 32.0
    tent(bt, rx, ry, 4.6, 4.0, 2.7, 0, 1, 2)
    bt.box((1.6, 0.8, 0.08), (rx - 3.4, ry - 2.6, 0.9), mi=4)
    for sx in (-0.7, 0.7):
        for sy in (-0.3, 0.3):
            bt.box((0.07, 0.07, 0.9), (rx - 3.4 + sx, ry - 2.6 + sy, 0.45), mi=4)
    bt.box((0.8, 0.5, 0.5), (rx - 3.5, ry - 2.6, 1.2), mi=3)
    bt.box((0.12, 0.04, 0.1), (rx - 3.65, ry - 2.86, 1.25), mi=5)
    ax, ay = rx + 3.0, ry + 0.6
    bt.cone(0.11, 0.05, 8.6, (ax, ay, 0), segs=6, mi=2)
    bt.box((0.9, 0.06, 0.06), (ax, ay, 8.0), mi=2)
    bt.box((0.6, 0.06, 0.06), (ax, ay, 7.3), mi=2)
    bt.finish()
    multi_tube("guys", [[(ax, ay, 7.6), (ax + dx, ay + dy, 0)] for dx, dy in ((-3, -2.4), (2.6, -2.2), (0.5, 3))],
               0.025, pole)
    stations["radio"] = (rx, ry, 2.7 + 0.4)
    bt = Batch("lamp_radio", [pole, glow_w])
    lantern_post(bt, rx - 4.6, ry - 2.0, 2.4, 0, 1)
    bt.finish()

    # Relic crate (centre front), glowing mint
    bt = Batch("crate", [M(N("#7a5f3e", 0.3)), M(N("#5a442c", 0.3)), glow_m, M("#bdfde0", emissive=True)])
    cx, cy = 0.5, 26.0
    bt.box((1.8, 1.2, 0.9), (cx, cy, 0.45))
    for zz in (0.15, 0.75):
        bt.box((1.86, 1.26, 0.12), (cx, cy, zz), mi=1)
    for xx in (-0.85, 0.85):
        bt.box((0.12, 1.26, 0.92), (cx + xx, cy, 0.46), mi=1)
    bt.box((1.66, 1.06, 0.08), (cx, cy, 0.9), mi=2)
    for i in range(7):
        bt.ico(rnd.uniform(0.14, 0.24), (cx + rnd.uniform(-0.6, 0.6), cy + rnd.uniform(-0.35, 0.35), 0.98),
               mi=3 if i % 3 == 0 else 2, sub=0, scale=(1, 1, 1.4))
    bt.box((1.9, 0.12, 1.1), (cx, cy + 0.9, 1.15), rot=(-28, 0, 0), mi=0)
    bt.finish()
    stations["crate"] = (cx, cy, 1.45)

    # Jeep (fictional, unmarked)
    bt = Batch("jeep", [M(N("#5c6340")), M(N("#353827")), M(N("#222220")), M(N("#7d8a90"))])
    jeep(bt, -1.5, 37.5, (0, 1, 2, 3), yaw=-14)
    bt.finish()

    # Sandbag walls
    bag = [M(N("#857650", 0.5), patches=[(0.55, N("#7b6c48", 0.5))], patch_scale=3.0)]
    bt = Batch("sandbags", bag, outline=0.9)
    sandbag_row(bt, [(-7.0, 22.5), (-4.0, 21.6), (-1.5, 21.4)], rnd, bag, rows=3)
    sandbag_row(bt, [(2.6, 21.4), (5.0, 21.6), (8.0, 22.6)], rnd, bag, rows=3)
    sandbag_row(bt, [(13.8, 28.5), (15.2, 30.5), (15.4, 33.5)], rnd, bag)
    sandbag_row(bt, [(-13.5, 34.0), (-14.0, 31.0), (-13.0, 28.4)], rnd, bag, rows=2)
    bt.finish(smooth=True)

    # dirt track into the yard + supply clutter in the foreground
    track = ground_mat("g_track_b", N("#6f604a", 0.5), [(0.5, N("#655744", 0.5))], patch_scale=0.4)
    strip_mesh("track", [(0.5 + 1.5 * math.sin(t * 0.25), 6 + t * 2.0, 0) for t in range(10)], 4.2, track, z=0.02)
    bt = Batch("supplies", [M(N("#6e5a3e", 0.35)), M(N("#4a5a3e", 0.35)), M(N("#3b3a33"))])
    for cx_, cy_, s_, mi_ in ((-6.5, 18.0, 1.0, 0), (-5.4, 18.4, 0.8, 0), (-6.1, 18.2, 0.65, 1)):
        bt.box((s_, s_ * 0.8, s_ * 0.7), (cx_, cy_, s_ * 0.35 + (0.7 if mi_ == 1 else 0)), mi=mi_,
               rot=(0, 0, rnd.uniform(-20, 20)))
    for bx_, by_ in ((6.8, 18.2), (7.5, 18.7), (6.9, 19.3)):
        bt.cone(0.4, 0.4, 1.1, (bx_, by_, 0), segs=12, mi=1)
        bt.cone(0.42, 0.42, 0.08, (bx_, by_, 0.75), segs=12, mi=2)
    bt.finish()
    # yard lantern posts
    bt = Batch("lamps", [pole, glow_w])
    lantern_post(bt, 6.8, 28.5, 2.6, 0, 1)
    bt.box((0.24, 0.24, 0.3), (-5.2, 18.5, 1.0), mi=1)
    lantern_post(bt, -9.1, 29.4, 2.6, 0, 1) if False else None
    bt.finish()
    # fence, trees, hills
    bt = Batch("fence", [pole], outline=0.8)
    fence(bt, -30, -14, 52, rnd)
    fence(bt, 18, 34, 54, rnd)
    bt.finish()
    tree_c = [M(N("#3e3428", 0.55)), M(N("#3a4a30", 0.55)), M(N("#33422c", 0.55))]
    bt = Batch("trees", tree_c, outline=0.7)
    for x, y in ((-20, 58), (-14, 64), (22, 62), (28, 70), (2, 72), (-30, 70)):
        tree_round(bt, x, y, rnd.uniform(3.0, 4.0), rnd, leaf_mi=1 + rnd.randint(0, 1))
    bt.finish()
    bt = Batch("trees_far", tree_c, outline=0)
    for i in range(50):
        tree_round(bt, rnd.uniform(-200, 200), rnd.uniform(110, 200), rnd.uniform(3.5, 6.0), rnd,
                   leaf_mi=1 + i % 2)
    bt.finish()
    mountains("ridge", 900, 1200, 60, rnd, M("#2a3352"), n=30, jag=0.3)

    sun_for(cfg["key"], 0.7)
    raw = render_raw(sc, "base")
    fg = Image.open(raw).convert("RGBA")
    sky = paint_sky(cfg, cfg["seed"])
    # moon disc
    d = ImageDraw.Draw(sky)
    mx, my, mr = 0.78 * BG_W, 0.13 * BG_H, 26
    d.ellipse((mx - mr, my - mr, mx + mr, my + mr), fill=(226, 230, 214))
    for ox, oy, rr in ((-8, -6, 6), (7, 5, 8), (-3, 11, 4)):
        d.ellipse((mx + ox - rr, my + oy - rr, mx + ox + rr, my + oy + rr), fill=(204, 210, 198))
    sky = sky.convert("RGBA")
    img = Image.alpha_composite(sky, fg).convert("RGB")
    img = bloom(img, thr=0.62, radius=16, amount=0.75)
    img = bloom(img, thr=0.75, radius=40, amount=0.4)
    img = grade(img, cfg)
    path = os.path.join(BG_DIR, "base.jpg")
    size = save_jpeg(img, path, 82, 350)
    st = {}
    for k in ("command", "barracks", "armory", "radio", "crate"):
        co = world_to_camera_view(sc, cam, Vector(stations[k]))
        st[k] = [round(co.x, 4), round(1 - co.y, 4)]
    print(f"[bg] base: {size // 1024} KB stations={st} ({time.time() - t0:.1f}s)", flush=True)
    return {"file": "base.jpg", "w": BG_W, "h": BG_H, "stations": st}
# ==========================================================================
# main
# ==========================================================================
def _load_json(p):
    if os.path.exists(p):
        try:
            with open(p) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _write_json(p, d):
    with open(p, "w") as f:
        json.dump(d, f, indent=2)
        f.write("\n")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    bg_names = list(BACKDROPS) + ["base"]
    map_names = list(MAPS)
    targets = []
    for a in args:
        if a == "backdrops":
            targets += bg_names
        elif a == "maps":
            targets += map_names
        elif a in bg_names or a in MAPS:
            targets.append(a)
        else:
            print(f"unknown target {a!r}; known: {bg_names + map_names}")
            sys.exit(2)
    if not targets:
        targets = bg_names + map_names
    os.makedirs(BG_DIR, exist_ok=True)
    os.makedirs(MAP_DIR, exist_ok=True)
    t0 = time.time()
    bg_meta = _load_json(os.path.join(BG_DIR, "bg.json"))
    map_meta = _load_json(os.path.join(MAP_DIR, "maps.json"))
    for t in targets:
        if t in MAPS:
            map_meta[t] = render_map(t)
            _write_json(os.path.join(MAP_DIR, "maps.json"),
                        {k: map_meta[k] for k in map_names if k in map_meta})
        else:
            bg_meta[t] = render_backdrop(t)
            _write_json(os.path.join(BG_DIR, "bg.json"),
                        {k: bg_meta[k] for k in bg_names if k in bg_meta})
    if not os.environ.get("KEEP_RAW") and os.path.isdir(TMP_DIR):
        shutil.rmtree(TMP_DIR, ignore_errors=True)
    print(f"[world] done in {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
