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
# BACKDROPS (filled in below)
# ==========================================================================
BACKDROPS = {}
BG_W, BG_H = 1600, 900


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
    bg_names = list(BACKDROPS)
    map_names = list(MAPS)
    targets = []
    for a in args:
        if a == "backdrops":
            targets += bg_names
        elif a == "maps":
            targets += map_names
        elif a in BACKDROPS or a in MAPS:
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
