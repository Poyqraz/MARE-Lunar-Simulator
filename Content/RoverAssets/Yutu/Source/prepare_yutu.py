"""
Blender (headless): Yutu (tashtego, CC-BY-4.0) prepared for the simulator.

  1. The floor is dropped; the rover is turned so its wheel lines run along X,
     centred between the six wheel hubs, ground at z = 0, scaled to real size.
  2. Each wheel = its hub (the six identical 252-vertex parts) plus every loose
     piece within the wheel's radius of its axle and its width.
  3. Exports body.glb (everything else) and wheel.glb (one wheel, origin on its
     axle, axle along Y), and wheels.json (the six axle centres, metres).
  4. Renders top and side previews: wheels coloured, body grey.

Usage: blender -b --factory-startup --disable-autoexec --python prepare_yutu.py -- <scene.gltf> <out dir> [flip]
"""
import json
import math
import os
import sys

import bpy
import bmesh
from mathutils import Matrix, Vector

args = sys.argv[sys.argv.index("--") + 1:]
SRC, OUT = args[0], args[1]
FLIP = len(args) > 2 and args[2] == "flip"     # turn 180 deg if the front came out backwards
SCALE = 2.0                                    # model 0.6 m tall -> real Yutu ~1.2 m
HUB_VERTS = 252
WHEEL_RADIUS = 0.085                           # model units, around the axle
WHEEL_HALF_WIDTH = 0.07
os.makedirs(OUT, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)
for o in list(bpy.context.scene.objects):
    if o.type == "MESH" and any(m and m.name == "Floor" for m in o.data.materials):
        bpy.data.objects.remove(o, do_unlink=True)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]

# Bake world transforms into the meshes, so everything is in one frame
for o in meshes:
    o.data.transform(o.matrix_world)
    o.parent = None
    o.matrix_world = Matrix.Identity(4)
for o in list(bpy.context.scene.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o, do_unlink=True)


def loose_parts(obj):
    """Lists of vertex indices, one per connected piece."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    seen, parts = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        stack, group = [v], []
        seen.add(v.index)
        while stack:
            x = stack.pop()
            group.append(x.index)
            for e in x.link_edges:
                y = e.other_vert(x)
                if y.index not in seen:
                    seen.add(y.index)
                    stack.append(y)
        parts.append(group)
    bm.free()
    return parts


def centre(obj, idx):
    pts = [obj.data.vertices[i].co for i in idx]
    lo = Vector([min(p[k] for p in pts) for k in range(3)])
    hi = Vector([max(p[k] for p in pts) for k in range(3)])
    return (lo + hi) / 2, hi - lo


color = next(o for o in meshes if any(m and m.name == "Yutu_color" for m in o.data.materials))
hubs = [centre(color, p)[0] for p in loose_parts(color) if len(p) == HUB_VERTS]
assert len(hubs) == 6, f"expected 6 hubs, found {len(hubs)}"

# Heading: the principal axis of the six hubs in XY (the wheel lines are longer
# than the track, so the hubs spread most along the rover)
mean = sum(hubs, Vector()) / 6
sxx = sum((h.x - mean.x) ** 2 for h in hubs)
syy = sum((h.y - mean.y) ** 2 for h in hubs)
sxy = sum((h.x - mean.x) * (h.y - mean.y) for h in hubs)
axis = 0.5 * math.atan2(2 * sxy, sxx - syy)
yaw = -axis + (math.pi if FLIP else 0.0)
to_rover = (Matrix.Scale(SCALE, 4) @ Matrix.Rotation(yaw, 4, "Z") @ Matrix.Translation(Vector((-mean.x, -mean.y, 0))))
for o in meshes:
    o.data.transform(to_rover)
    o.data.update()
hubs = [to_rover @ h for h in hubs]
ground = min(min((v.co.z for v in o.data.vertices)) for o in meshes)
for o in meshes:
    o.data.transform(Matrix.Translation(Vector((0, 0, -ground))))
hubs = [h - Vector((0, 0, ground)) for h in hubs]
R, W = WHEEL_RADIUS * SCALE, WHEEL_HALF_WIDTH * SCALE

# Split each wheel out of every mesh (both materials can be on a wheel)
wheel_objs = {i: [] for i in range(6)}
for o in meshes:
    parts = loose_parts(o)
    assign = {}
    for p in parts:
        c, size = centre(o, p)
        for i, h in enumerate(hubs):
            radial = math.hypot(c.x - h.x, c.z - h.z)
            if radial <= R and abs(c.y - h.y) <= W and max(size.x, size.z) <= 2.2 * R:
                assign.setdefault(i, []).extend(p)
                break
    # Every wheel is cut from the untouched mesh (vertex indices stay valid),
    # then all wheel vertices leave the body in one step.
    original = bmesh.new()
    original.from_mesh(o.data)
    for i, idx in assign.items():
        keep = set(idx)
        wheel_bm = original.copy()
        wheel_bm.verts.ensure_lookup_table()
        bmesh.ops.delete(wheel_bm, geom=[v for v in wheel_bm.verts if v.index not in keep], context="VERTS")
        me = bpy.data.meshes.new(f"wheel_{i}_{o.name}")
        wheel_bm.to_mesh(me)
        wheel_bm.free()
        for m in o.data.materials:
            me.materials.append(m)
        ob = bpy.data.objects.new(me.name, me)
        bpy.context.scene.collection.objects.link(ob)
        wheel_objs[i].append(ob)
    every = set(v for idx in assign.values() for v in idx)
    original.verts.ensure_lookup_table()
    bmesh.ops.delete(original, geom=[v for v in original.verts if v.index in every], context="VERTS")
    original.to_mesh(o.data)
    o.data.update()
    original.free()

# Name the wheels by position: front/middle/back, left (+y) / right (-y)
order = sorted(range(6), key=lambda i: -hubs[i].x)
names = {}
for i in order:
    side = "L" if hubs[i].y > 0 else "R"
    row = sorted([j for j in range(6) if (hubs[j].y > 0) == (hubs[i].y > 0)], key=lambda j: -hubs[j].x)
    names[i] = ("F", "M", "B")[row.index(i)] + side
info = {names[i]: [round(c, 4) for c in hubs[i]] for i in range(6)}
info["_scale"], info["_flip"] = SCALE, FLIP
info["_wheel_parts"] = {names[i]: sum(len(o.data.vertices) for o in wheel_objs[i]) for i in range(6)}

# Previews: wheels coloured, body grey (Workbench, object colours)
for o in meshes:
    o.color = (0.6, 0.6, 0.6, 1)
palette = [(1, 0.2, 0.2, 1), (0.2, 0.9, 0.2, 1), (0.2, 0.4, 1, 1), (1, 0.8, 0.1, 1), (1, 0.3, 1, 1), (0.1, 0.9, 0.9, 1)]
for i in range(6):
    for ob in wheel_objs[i]:
        ob.color = palette[i]
scene = bpy.context.scene
scene.render.engine = "BLENDER_WORKBENCH"
scene.display.shading.color_type = "OBJECT"
scene.display.shading.light = "STUDIO"
scene.render.resolution_x, scene.render.resolution_y = 900, 600
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = 2.6
for view, loc, rot in (("top", (0, 0, 5), (0, 0, 0)), ("side", (0, -5, 0.6), (math.pi / 2, 0, 0)),
                       ("front", (5, 0, 0.6), (math.pi / 2, 0, math.pi / 2))):
    cam.location, cam.rotation_euler = loc, rot
    scene.render.filepath = os.path.join(OUT, f"preview_{view}.png")
    bpy.ops.render.render(write_still=True)

# Exports: the body, and one wheel (front-left) moved to its axle
def export(objs, path):
    bpy.ops.object.select_all(action="DESELECT")
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.gltf(filepath=path, use_selection=True, export_format="GLB", export_yup=True)

bpy.data.objects.remove(cam, do_unlink=True)

# Mounting points (rover frame, metres): the mast head (highest piece), the
# chassis box (the body without wings, mast, dish and arm), its front and rear.
body_pts = [v.co.copy() for o in meshes for v in o.data.vertices]
top = max(body_pts, key=lambda p: p.z)
head = [p for p in body_pts if p.z > top.z - 0.12]
info["mast_head"] = [round(sum(p[k] for p in head) / len(head), 4) for k in range(3)]
chassis = [p for p in body_pts if abs(p.y) < 0.42 and 0.25 < p.z < 0.9 and abs(p.x) < 0.75]
info["chassis_min"] = [round(min(p[k] for p in chassis), 4) for k in range(3)]
info["chassis_max"] = [round(max(p[k] for p in chassis), 4) for k in range(3)]
info["overall_min"] = [round(min(p[k] for p in body_pts), 4) for k in range(3)]
info["overall_max"] = [round(max(p[k] for p in body_pts), 4) for k in range(3)]


def join(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for ob in objs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    if len(objs) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = ob.data.name = name
    return ob


# One object per part (both materials as slots): Yutu_Body, and Yutu_Wheel (the
# front-left wheel, moved to its axle); the other five wheels are not exported.
fl = next(i for i in range(6) if names[i] == "FL")
h = hubs[fl]
for ob in wheel_objs[fl]:
    ob.data.transform(Matrix.Translation(-h))
    ob.data.update()
for i in range(6):
    if i != fl:
        for ob in wheel_objs[i]:
            bpy.data.objects.remove(ob, do_unlink=True)
body = join(meshes, "Yutu_Body")
wheel = join(wheel_objs[fl], "Yutu_Wheel")
bpy.ops.object.select_all(action="DESELECT")
body.select_set(True)
wheel.select_set(True)
bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, "yutu.glb"), use_selection=True, export_format="GLB", export_yup=True)
json.dump(info, open(os.path.join(OUT, "wheels.json"), "w"), indent=1)
print("PREPARE", json.dumps(info))
