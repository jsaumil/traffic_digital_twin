"""Real junction scene from OpenStreetMap geometry (config/junction.json), SI coordinates shared with model."""
import math
import bpy
from mathutils import Vector
from blender.materials import enum, function_enum, material
from simulation.geometry import offset, point_at, resample
from simulation.junction import ARMS, DATA, LEFT_HAND

SCENE_NAME = "Traffic Digital Twin | " + DATA["name"]
VEHICLES_COLLECTION = "TR | 06 Live Vehicles"


def build_scene():
    # Earlier twin scenes (another junction) would hold the stable object names; retire them.
    for stale in [s for s in bpy.data.scenes if s.name.startswith("Traffic Digital Twin | ") and s.name != SCENE_NAME]:
        for obj in list(stale.objects):
            if obj.get("traffic_owned"):
                bpy.data.objects.remove(obj, do_unlink=True)
        if len(bpy.data.scenes) > 1:
            bpy.data.scenes.remove(stale)
    scene = bpy.data.scenes.get(SCENE_NAME) or bpy.data.scenes.new(SCENE_NAME)
    if bpy.context.window:
        bpy.context.window.scene = scene
    for obj in list(scene.objects):
        if obj.get("traffic_owned"):
            bpy.data.objects.remove(obj, do_unlink=True)
    root = bpy.data.collections.get("TR | TRAFFIC DIGITAL TWIN") or bpy.data.collections.new("TR | TRAFFIC DIGITAL TWIN")
    if root.name not in scene.collection.children:
        scene.collection.children.link(root)
    groups = {}
    for name in ("00 Site", "01 Roads", "02 Markings", "03 Signals", "04 Streetscape", "05 Buildings", "06 Live Vehicles", "07 Instruments", "08 Lighting"):
        collection = bpy.data.collections.get("TR | "+name) or bpy.data.collections.new("TR | "+name)
        if collection.name not in root.children:
            root.children.link(collection)
        groups[name] = collection

    def own(obj, name, group, mat=None):
        obj.name = "TR."+name
        obj["traffic_owned"] = True
        for collection in list(obj.users_collection):
            collection.objects.unlink(obj)
        groups[group].objects.link(obj)
        if mat:
            obj.data.materials.clear(); obj.data.materials.append(mat)
        return obj

    asphalt = material("Asphalt", (0.042,0.057,0.075), roughness=0.95)
    concrete = material("Concrete", (0.38,0.44,0.47), roughness=0.85)
    dark = material("Graphite", (0.017,0.028,0.044), metallic=0.5)
    white = material("Road.White", (0.82,0.86,0.83), roughness=0.8)
    yellow = material("Road.Yellow", (0.96,0.63,0.05))
    grass = material("Landscape", (0.10,0.24,0.19))
    green = material("Foliage", (0.08,0.3,0.21))
    teal = material("Accent", (0.03,0.78,0.69), emission=0.35)
    text_mat = material("Text", (0.75,0.89,0.94), emission=0.4)
    window_mat = material("Building.Windows", (0.11,0.25,0.32), metallic=0.6, roughness=0.25)
    facade_mats = [material("Facade."+str(i), color) for i,color in enumerate(((0.38,0.46,0.51),(0.58,0.57,0.51),(0.22,0.32,0.36),(0.42,0.36,0.33)))]

    def cube(name, loc, size, mat, group="04 Streetscape", bevel=0):
        bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
        obj = own(bpy.context.object, name, group, mat)
        obj.dimensions = size
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        if bevel:
            mod = obj.modifiers.new("Edge highlights", "BEVEL")
            mod.width, mod.segments = bevel, 2
        return obj

    def cylinder(name, loc, radius, depth, mat, group="04 Streetscape"):
        bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=radius, depth=depth, location=loc)
        obj = own(bpy.context.object, name, group, mat)
        for face in obj.data.polygons:
            face.use_smooth = len(face.vertices)==4
        return obj

    def sphere(name, loc, radius, mat, group="04 Streetscape"):
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, radius=radius, location=loc)
        obj = own(bpy.context.object, name, group, mat)
        for face in obj.data.polygons:
            face.use_smooth = True
        return obj

    def text(name, body, loc, size=1, mat=text_mat, vertical=False):
        data = bpy.data.curves.new("TR."+name, type=function_enum(bpy.data.curves,"new","type","FONT"))
        data.body, data.size, data.extrude = body, size, 0.003
        obj = bpy.data.objects.new("TR."+name,data)
        own(obj,name,"07 Instruments",mat)
        obj.location = loc
        if vertical:
            obj.rotation_euler.x = math.pi/2
        return obj

    def mesh_object(name, vertices, faces, group, mat):
        data = bpy.data.meshes.new("TR."+name)
        data.from_pydata(vertices, [], faces)
        return own(bpy.data.objects.new("TR."+name, data), name, group, mat)

    def ribbon(name, points, a, b, z, group, mat):
        """Flat strip between lateral offsets a and b (left of travel direction) along a polyline."""
        left, right = offset(points, a), offset(points, b)
        vertices = [(x, y, z) for x, y in left] + [(x, y, z) for x, y in right]
        n = len(points)
        faces = [(i, i + 1, n + i + 1, n + i) for i in range(n - 1)]
        return mesh_object(name, vertices, faces, group, mat)

    def dashes(points, lateral, z, length=3.0, gap=3.0, width=0.12):
        """Dashed lane line as quads, appended to a shared vertex/face list."""
        total = sum(math.dist(p, q) for p, q in zip(points, points[1:]))
        quads, s = [], 0.0
        while s + length < total:
            segment = offset([point_at(points, s), point_at(points, s + length)], lateral)
            (x0, y0), (x1, y1) = segment
            dx, dy = (x1 - x0) / length, (y1 - y0) / length
            nx, ny = -dy * width / 2, dx * width / 2
            quads.append([(x0 + nx, y0 + ny, z), (x1 + nx, y1 + ny, z), (x1 - nx, y1 - ny, z), (x0 - nx, y0 - ny, z)])
            s += length + gap
        return quads

    def quads_object(name, quads, group, mat):
        vertices = [v for quad in quads for v in quad]
        return mesh_object(name, vertices, [tuple(range(4 * i, 4 * i + 4)) for i in range(len(quads))], group, mat)

    extent = max(arm.extent for arm in ARMS.values())
    size = 2 * extent + 24
    cube("site.plinth", (0,0,-1.1), (size,size,2.2), dark, "00 Site", 1.1)
    cube("site.ground", (0,0,-0.12), (size-2,size-2,0.28), grass, "00 Site")
    lhs = 1 if LEFT_HAND else -1  # Outbound carriageway is on the left of the outward axis.
    box = DATA["box"]
    mesh_object("junction.box", [(x, y, 0.06) for x, y in box], [tuple(range(len(box)))], "01 Roads", asphalt)
    for arm in ARMS.values():
        m, inw, outw = arm.median / 2, arm.in_lanes * arm.lane_width, arm.out_lanes * arm.lane_width
        road = resample(arm.axis, arm.stop - 4, arm.extent)
        beyond = resample(arm.axis, arm.stop, arm.extent)
        ribbon(f"carriageway.{arm.id}", road, lhs * (m + outw), -lhs * (m + inw), 0.06, "01 Roads", asphalt)
        if m:
            ribbon(f"median.{arm.id}", beyond, m, -m, 0.22, "01 Roads", concrete)
        for side, edge in (("out", lhs * (m + outw)), ("in", -lhs * (m + inw))):
            outer = edge + math.copysign(3.0, edge)
            ribbon(f"footpath.{arm.id}.{side}", resample(arm.axis, arm.stop + 2, arm.extent), outer, edge, 0.17, "01 Roads", concrete)
            ribbon(f"kerb.{arm.id}.{side}", resample(arm.axis, arm.stop + 2, arm.extent),
                   edge + math.copysign(0.2, edge), edge, 0.19, "01 Roads", white)
        lines = []
        for k in range(1, arm.in_lanes):
            lines += dashes(beyond, -lhs * (m + k * arm.lane_width), 0.075)
        for k in range(1, arm.out_lanes):
            lines += dashes(beyond, lhs * (m + k * arm.lane_width), 0.075)
        if lines:
            quads_object(f"lanes.{arm.id}", lines, "02 Markings", white)
        stopline = resample(arm.axis, arm.stop, arm.stop + 0.45, 0.45)
        ribbon(f"stopline.{arm.id}", stopline, -lhs * m, -lhs * (m + inw), 0.08, "02 Markings", white)
        zebra, lateral = [], -(m + inw) + 0.4
        while lateral < m + outw - 0.4:
            strip = offset(resample(arm.axis, arm.stop - 3.6, arm.stop - 0.8, 2.8), lateral)
            (x0, y0), (x1, y1) = strip
            dx, dy = (x1 - x0) / 2.8, (y1 - y0) / 2.8
            nx, ny = -dy * 0.25, dx * 0.25
            zebra.append([(x0+nx, y0+ny, 0.08), (x1+nx, y1+ny, 0.08), (x1-nx, y1-ny, 0.08), (x0-nx, y0-ny, 0.08)])
            lateral += 1.0
        quads_object(f"crosswalk.{arm.id}", zebra, "02 Markings", white)
        label = point_at(arm.axis, arm.extent - 10)
        side = offset([point_at(arm.axis, arm.extent - 11), label], -lhs * (m + inw + 4.5))[1]
        text("approach."+arm.id, f"{arm.id}  {arm.name.upper()}", (side[0], side[1], 0.3), 2.4, teal)
        # Signal heads stand on the near-side kerb at the stop line, facing approaching traffic.
        px, py = offset(resample(arm.axis, arm.stop, arm.stop + 1, 1), -lhs * (m + inw + 1.2))[0]
        nx, ny = arm.outward
        cylinder(f"signal.pole.{arm.id}", (px,py,2.8), 0.13, 5.6, dark, "03 Signals")
        housing = cube(f"signal.housing.{arm.id}", (px,py,5.2), (0.92,0.65,2.7), dark, "03 Signals", 0.12)
        housing.rotation_euler.z = math.atan2(ny,nx)-math.pi/2
        for color,z in (("RED",6.02),("YELLOW",5.2),("GREEN",4.38)):
            lamp = sphere(f"signal.{arm.id}.{color}", (px+nx*0.39,py+ny*0.39,z), 0.32, dark, "03 Signals")
            lamp["signal_group"] = arm.id
            lamp["entity_id"] = f"signal_{arm.id}_{color}"
        # Median streetlights, as on Ahmedabad's divided arterials.
        for distance in range(int(arm.stop) + 10, int(arm.extent), 30):
            lx, ly = point_at(arm.axis, distance)
            cylinder(f"streetlight.{arm.id}.{distance}", (lx,ly,4.2), 0.09, 8, dark)
            for sign in (-1, 1):
                ox, oy = offset([point_at(arm.axis, distance), point_at(arm.axis, distance + 1)], sign * 1.4)[0]
                cube(f"streetlight.head.{arm.id}.{distance}.{sign}", (ox,oy,8.1), (0.9,0.5,0.15), white)
        # Queue instrument beside each arm's footpath.
        qx, qy = offset([point_at(arm.axis, 55), point_at(arm.axis, 56)], -lhs * (m + inw + 6))[0]
        text("text.queue."+arm.id, f"{arm.id} / -- QUEUED", (qx, qy, 0.48), 1.6, teal)
    # OpenStreetMap building footprints, extruded (OSM height/levels, else 3-6 storeys).
    for index, building in enumerate(DATA["buildings"]):
        footprint = building["footprint"]
        height = building["height"] or 9 + (building["osm_id"] % 4) * 3
        n = len(footprint)
        vertices = [(x, y, 0.2) for x, y in footprint] + [(x, y, height) for x, y in footprint]
        faces = [tuple(range(n - 1, -1, -1)), tuple(range(n, 2 * n))] + [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
        obj = mesh_object(f"building.{index}", vertices, faces, "05 Buildings", facade_mats[building["osm_id"] % len(facade_mats)])
        obj["osm_id"] = building["osm_id"]

    # World-space live instrumentation above the north-west edge.
    top = extent + 6
    cube("header.panel",(0,top,16),(2*extent,0.8,13),dark,"07 Instruments",0.5)
    text("title",DATA["name"].upper(),(-extent+3,top-0.5,18.5),3.1,vertical=True)
    text("text.connection","CONNECTING",(-extent+3,top-0.6,13.7),1.8,teal,True)
    text("text.clock","00000.0 s / STOPPED",(-extent*0.3,top-0.6,13.7),1.8,text_mat,True)
    text("text.phase","N GREEN / 40.0s",(extent*0.3,top-0.6,13.7),1.8,text_mat,True)
    text("text.metrics","QUEUED ---   ACTIVE ---   PASSED ----",(-extent+3,-top,-0.3),2.1,teal,True)
    text("attribution","Map data (c) OpenStreetMap contributors",(extent-60,-top,-0.3),1.4,text_mat,True)

    camera_data=bpy.data.cameras.new("TR.Observer")
    camera=bpy.data.objects.new("TR.camera",camera_data)
    own(camera,"camera","08 Lighting")
    camera.location=(extent*0.75,-extent*0.95,extent*1.25)
    camera.rotation_euler=(Vector((0,0,7))-camera.location).to_track_quat('-Z','Y').to_euler()
    enum(camera_data,"type","ORTHO")
    camera_data.ortho_scale=extent*2.25
    camera_data.clip_end=1000
    scene.camera=camera
    detail_data=bpy.data.cameras.new("TR.DetailObserver")
    detail=bpy.data.objects.new("TR.camera.detail",detail_data)
    own(detail,"camera.detail","08 Lighting")
    detail.location=(38,-47,76)
    detail.rotation_euler=(Vector((0,0,0))-detail.location).to_track_quat('-Z','Y').to_euler()
    enum(detail_data,"type","ORTHO")
    detail_data.ortho_scale=86
    detail_data.clip_end=1000
    for name,location,energy,size in (("key",(0,-35,150),300000,140),("fill",(-110,-10,100),200000,110),("rim",(30,110,120),250000,100)):
        data=bpy.data.lights.new("TR."+name,type=function_enum(bpy.data.lights,"new","type","AREA"))
        data.energy,data.size=energy,size
        obj=bpy.data.objects.new("TR."+name,data)
        own(obj,name,"08 Lighting")
        obj.location=location
        obj.rotation_euler=(Vector((0,0,0))-obj.location).to_track_quat('-Z','Y').to_euler()
    world=bpy.data.worlds.get("TR.World") or bpy.data.worlds.new("TR.World")
    world.use_nodes=True
    bg=next(n for n in world.node_tree.nodes if n.type=="BACKGROUND")
    bg.inputs["Color"].default_value=(0.08,0.12,0.18,1)
    bg.inputs["Strength"].default_value=0.4
    scene.world=world
    enum(scene.unit_settings,"system","METRIC")
    scene.unit_settings.scale_length=1
    scene.render.resolution_x,scene.render.resolution_y=1800,1200
    scene.render.resolution_percentage=100
    scene["traffic_schema"]=1
    scene["traffic_endpoint"]="ws://127.0.0.1:8875/ws"
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=="VIEW_3D":
                enum(area.spaces.active.shading,"type","MATERIAL")
                enum(area.spaces.active.region_3d,"view_perspective","CAMERA")
                area.spaces.active.overlay.show_overlays=False
    # Initialize all signal lamps using the same signal state as the physics engine.
    from simulation.engine import Engine
    from blender.signal_renderer import SignalRenderer
    from blender.vehicle_renderer import VehicleRenderer
    from blender import dashboard_overlay
    initial=Engine().snapshot()
    SignalRenderer().apply(initial["signals"])
    VehicleRenderer(groups["06 Live Vehicles"]).apply(initial["vehicles"])
    dashboard_overlay.update(initial,False)
    for blocks in (bpy.data.meshes,bpy.data.curves,bpy.data.cameras,bpy.data.lights):
        for block in list(blocks):
            if block.name.startswith("TR.") and block.users==0 and not block.name.startswith("TR.Mesh."):
                blocks.remove(block)
    return scene
