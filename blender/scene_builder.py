"""Procedural right-hand-traffic urban intersection, SI coordinates shared with model."""
import math
import bpy
from mathutils import Vector
from blender.materials import enum, function_enum, material
from simulation.lane import APPROACHES, OUTWARD, LANE_WIDTH, ROAD_HALF_WIDTH

SCENE_NAME = "Traffic Digital Twin | Four-way Junction"
VEHICLES_COLLECTION = "TR | 06 Live Vehicles"


def build_scene():
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

    cube("site.plinth", (0,0,-1.1), (150,150,2.2), dark, "00 Site", 1.1)
    cube("site.paving", (0,0,-0.12), (148,148,0.28), concrete, "00 Site")
    w,c,L = ROAD_HALF_WIDTH,11,73
    outline = [(-w,-L),(w,-L),(w,-c),(c,-c),(c,-w),(L,-w),(L,w),(c,w),(c,c),(w,c),(w,L),(-w,L),(-w,c),(-c,c),(-c,w),(-L,w),(-L,-w),(-c,-w),(-c,-c),(-w,-c)]
    mesh = bpy.data.meshes.new("TR.RoadSurface")
    mesh.from_pydata([(x,y,0.06) for x,y in outline], [], [tuple(range(len(outline)))])
    road = bpy.data.objects.new("TR.roads",mesh)
    own(road,"roads","01 Roads",asphalt)
    # Raised sidewalks follow each road arm, with tactile curb edges.
    for approach in APPROACHES:
        nx,ny = OUTWARD[approach]
        dx,dy = -nx,-ny
        rx,ry = dy,-dx
        for side in (-1,1):
            center = (nx*42+rx*8.1*side,ny*42+ry*8.1*side,0.14)
            size = (3.2,62,0.22) if nx==0 else (62,3.2,0.22)
            cube(f"sidewalk.{approach}.{side}",center,size,concrete,"01 Roads",0.08)
            curb = (nx*42+rx*6.55*side,ny*42+ry*6.55*side,0.23)
            cube(f"curb.{approach}.{side}",curb,(0.18,62,0.28) if nx==0 else (62,0.18,0.28),white,"01 Roads")
        # Double yellow centerline, dashed lane separators and edge boundaries.
        for offset in (-0.14,0.14):
            position = (nx*42+rx*offset,ny*42+ry*offset,0.075)
            cube(f"centerline.{approach}.{offset}",position,(0.10,62,0.014) if nx==0 else (62,0.10,0.014),yellow,"02 Markings")
        for offset in (-3.2,3.2):
            for j,distance in enumerate(range(15,72,6)):
                cube(f"lane.{approach}.{offset}.{j}",(nx*distance+rx*offset,ny*distance+ry*offset,0.077),
                     (0.12,3,0.015) if nx==0 else (3,0.12,0.015),white,"02 Markings")
        # Stop line only across the approaching half, 11 m from intersection center.
        cube(f"stopline.{approach}",(nx*11+rx*3.2,ny*11+ry*3.2,0.08),
             (6.1,0.38,0.02) if nx==0 else (0.38,6.1,0.02),white,"02 Markings")
        for j in range(10):
            lateral = -5.85+j*1.3
            cube(f"crosswalk.{approach}.{j}",(nx*8.6+rx*lateral,ny*8.6+ry*lateral,0.08),
                 (0.75,2.4,0.02) if nx==0 else (2.4,0.75,0.02),white,"02 Markings")
        for lane in range(2):
            lateral=(lane+0.5)*LANE_WIDTH
            position=Vector((nx*27+rx*lateral,ny*27+ry*lateral,0.09))
            shaft=cube(f"arrow.shaft.{approach}.{lane}",position,(0.22,3.5,0.02),white,"02 Markings")
            yaw=math.atan2(dy,dx)-math.pi/2
            shaft.rotation_euler.z=yaw
            arrowmesh=bpy.data.meshes.new(f"TR.Arrow.{approach}.{lane}")
            tip=position+Vector((dx*2.7,dy*2.7,0))
            base=position+Vector((dx*1.2,dy*1.2,0))
            arrowmesh.from_pydata([tip,base+Vector((rx*0.8,ry*0.8,0)),base-Vector((rx*0.8,ry*0.8,0))],[],[(0,1,2)])
            own(bpy.data.objects.new("arrow",arrowmesh),f"arrow.head.{approach}.{lane}","02 Markings",white)
        text("approach."+approach,approach,(nx*54+rx*9.8-1,ny*54+ry*9.8-1,0.3),2.8,teal)
        # Signal heads sit at the near-side curb, facing their own approaching traffic.
        px,py=nx*12+rx*7.3,ny*12+ry*7.3
        cylinder(f"signal.pole.{approach}",(px,py,2.8),0.13,5.6,dark,"03 Signals")
        housing=cube(f"signal.housing.{approach}",(px,py,5.2),(0.92,0.65,2.7),dark,"03 Signals",0.12)
        housing.rotation_euler.z=math.atan2(ny,nx)-math.pi/2
        for color,z in (("RED",6.02),("YELLOW",5.2),("GREEN",4.38)):
            lamp=sphere(f"signal.{approach}.{color}",(px+nx*0.39,py+ny*0.39,z),0.32,dark,"03 Signals")
            lamp["signal_group"]=approach
            lamp["entity_id"]=f"signal_{approach}_{color}"
        for distance in (24,55):
            lx,ly=nx*distance+rx*8.4,ny*distance+ry*8.4
            cylinder(f"streetlight.{approach}.{distance}",(lx,ly,4),0.09,8,dark)
            cube(f"streetlight.arm.{approach}.{distance}",(lx-rx,ly-ry,7.9),(2.3,0.13,0.13) if nx==0 else (0.13,2.3,0.13),dark)
            cube(f"streetlight.head.{approach}.{distance}",(lx-rx*2,ly-ry*2,7.8),(0.8,0.8,0.15),white)

    for quadrant,(sx,sy) in enumerate(((-1,-1),(1,-1),(-1,1),(1,1))):
        cube(f"plaza.{quadrant}",(sx*33,sy*33,0.18),(40,40,0.32),concrete,"04 Streetscape",0.2)
        cube(f"park.{quadrant}",(sx*23,sy*28,0.4),(16,20,0.25),grass,"04 Streetscape",0.6)
        for i,(bx,by,height) in enumerate(((47,47,13+quadrant*2),(25,54,8+quadrant))):
            x,y=sx*bx,sy*by
            cube(f"building.{quadrant}.{i}",(x,y,height/2+0.5),(15,15,height),facade_mats[quadrant],"05 Buildings",0.25)
            cube(f"building.roof.{quadrant}.{i}",(x,y,height+0.7),(15.6,15.6,0.6),dark,"05 Buildings",0.12)
            for floor in range(2,int(height),3):
                cube(f"windows.front.{quadrant}.{i}.{floor}",(x,y-7.55,floor+0.6),(12,0.06,1.25),window_mat,"05 Buildings")
                cube(f"windows.side.{quadrant}.{i}.{floor}",(x+7.55,y,floor+0.6),(0.06,12,1.25),window_mat,"05 Buildings")
        for i,(tx,ty) in enumerate(((19,21),(29,21),(19,35),(30,35))):
            x,y=sx*tx,sy*ty
            cylinder(f"tree.trunk.{quadrant}.{i}",(x,y,1.5),0.25,3,dark)
            crown=sphere(f"tree.crown.{quadrant}.{i}",(x,y,4.3),2.4,green)
            crown.scale.z=1.2

    # World-space live instrumentation beside each arm and above the rear edge.
    for approach,(x,y) in {"N":(13,16),"S":(-38,-18),"E":(17,-18),"W":(-39,16)}.items():
        cube("queue.panel."+approach,(x+10,y+1,0.3),(24,4,0.3),dark,"07 Instruments",0.2)
        text("text.queue."+approach,f"{approach} / -- QUEUED",(x,y,0.48),1.15,teal)
    cube("header.panel",(0,71,16),(142,0.8,13),dark,"07 Instruments",0.5)
    text("title","NEXUS / TRAFFIC SIGNAL DIGITAL TWIN",(-67,70.5,18.5),3.1,vertical=True)
    text("text.connection","CONNECTING",(-67,70.4,13.7),1.8,teal,True)
    text("text.clock","00000.0 s / STOPPED",(-20,70.4,13.7),1.8,text_mat,True)
    text("text.phase","NS GREEN / 25.0s",(24,70.4,13.7),1.8,text_mat,True)
    text("text.metrics","QUEUED ---   ACTIVE ---   PASSED ----",(-66,-75.1,-0.3),2.1,teal,True)

    camera_data=bpy.data.cameras.new("TR.Observer")
    camera=bpy.data.objects.new("TR.camera",camera_data)
    own(camera,"camera","08 Lighting")
    camera.location=(95,-120,155)
    camera.rotation_euler=(Vector((0,0,7))-camera.location).to_track_quat('-Z','Y').to_euler()
    enum(camera_data,"type","ORTHO")
    camera_data.ortho_scale=255
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
    for name,location,energy,size in (("key",(0,-35,110),150000,90),("fill",(-70,-10,70),100000,75),("rim",(20,65,90),130000,65)):
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
