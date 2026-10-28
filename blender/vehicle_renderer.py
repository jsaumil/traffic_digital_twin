"""One linked-mesh object per vehicle; type prototypes built once, never per frame."""
import bpy
from blender.materials import material
from simulation.vehicle import TYPES


def prepare_meshes():
    glass = material("Vehicle.Glass", (0.025, 0.09, 0.15), metallic=0.6, roughness=0.18)
    tire = material("Vehicle.Tires", (0.012, 0.018, 0.024), roughness=0.85)
    headlamp = material("Vehicle.Headlamp", (0.9, 0.92, 0.68), emission=1.4)
    tail = material("Vehicle.Taillamp", (0.8, 0.025, 0.035), emission=0.6)
    meshes = {}
    palettes = [(0.04, 0.45, 0.7), (0.9, 0.28, 0.055), (0.7, 0.75, 0.8), (0.24, 0.1, 0.58)]
    for kind, (length, width, height, _) in TYPES.items():
        for variant in range(4):
            name = f"TR.Mesh.{kind}.{variant}"
            existing = bpy.data.meshes.get(name)
            if existing:
                meshes[kind, variant] = existing
                continue
            body = material(f"Vehicle.Body.{kind}.{variant}", palettes[variant] if kind == "car" else
                            {"bus": (0.92, 0.55, 0.07), "truck": (0.19, 0.5, 0.43), "motorcycle": (0.72, 0.15, 0.24),
                             "auto": (0.95, 0.78, 0.08)}[kind], metallic=0.35, roughness=0.28)
            vertices, faces, indices = [], [], []
            def box(center, size, mat_index):
                x, y, z = center
                sx, sy, sz = [s / 2 for s in size]
                base = len(vertices)
                vertices.extend([(x+dx*sx, y+dy*sy, z+dz*sz) for dx, dy, dz in
                                 [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]])
                for face in [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]:
                    faces.append(tuple(base+i for i in face)); indices.append(mat_index)
            if kind == "motorcycle":
                box((0,0,0.48),(0.45,length*0.7,0.45),0)
                box((0,-0.2,1.0),(0.5,0.45,0.7),0)  # stylized rider
                for y in (-length*0.35,length*0.35):
                    box((0,y,0.28),(0.22,0.5,0.55),2)
            elif kind == "auto":
                # Auto-rickshaw: low tub, canopy on pillars, one front and two rear wheels.
                box((0,0,0.55),(width,length*0.9,0.55),0)
                box((0,0.05,1.62),(width*1.02,length*0.8,0.12),1)
                for x in (-width*0.46,width*0.46):
                    for y in (-length*0.36,length*0.3):
                        box((x,y,1.2),(0.06,0.06,0.75),0)
                box((0,length*0.38,0.25),(0.18,0.45,0.45),2)
                for x in (-width*0.45,width*0.45):
                    box((x,-length*0.3,0.25),(0.18,0.45,0.45),2)
                box((0,length/2,0.7),(0.35,0.05,0.18),3)
            else:
                box((0,0,height*0.35),(width,length,height*0.45),0)
                cabin_length = length*0.85 if kind == "bus" else length*0.58 if kind == "car" else length*0.30
                cabin_y = 0 if kind != "truck" else length*0.29
                box((0,cabin_y,height*0.72),(width*0.89,cabin_length,height*0.48),1)
                box((0,cabin_y,height*0.98),(width*0.96,cabin_length*1.02,0.08),0)
                if kind == "truck":
                    box((0,-length*0.16,height*0.70),(width*0.98,length*0.59,height*0.60),0)
                for x in (-width*0.5,width*0.5):
                    for y in (-length*0.31,length*0.31):
                        box((x,y,0.35),(0.22,0.65,0.65),2)
                for x in (-width*0.32,width*0.32):
                    box((x,length/2+0.015,height*0.35),(0.35,0.05,0.20),3)
                    box((x,-length/2-0.015,height*0.35),(0.35,0.05,0.17),4)
            mesh = bpy.data.meshes.new(name)
            mesh.from_pydata(vertices, [], faces)
            for mat in (body, glass, tire, headlamp, tail):
                mesh.materials.append(mat)
            for polygon, index in zip(mesh.polygons, indices):
                polygon.material_index = index
            meshes[kind, variant] = mesh
    return meshes


class VehicleRenderer:
    def __init__(self, collection):
        self.collection = collection
        self.meshes = prepare_meshes()
        self.objects = {obj.get("entity_id"): obj for obj in collection.objects if obj.get("entity_id")}

    def apply(self, vehicles):
        for entity_id in list(self.objects):
            if entity_id not in vehicles:
                obj=bpy.data.objects.get("TR."+entity_id)
                if obj:
                    bpy.data.objects.remove(obj, do_unlink=True)
                self.objects.pop(entity_id)
        for entity_id, state in vehicles.items():
            obj = bpy.data.objects.get("TR."+entity_id)
            mesh = self.meshes[state["type"], int(entity_id.split("_")[1]) % 4]
            if obj is None:
                obj = bpy.data.objects.new("TR." + entity_id, mesh)
                self.collection.objects.link(obj)
                obj["entity_id"] = entity_id
                obj["traffic_owned"] = True
                bevel = obj.modifiers.new("Body edge highlights", "BEVEL")
                bevel.width, bevel.segments = 0.06, 2
                self.objects[entity_id] = obj
            if obj.data != mesh:
                obj.data = mesh
            if any(abs(a-b)>1e-5 for a,b in zip(obj.location,state["position"])):
                obj.location = state["position"]
            if abs(obj.rotation_euler.z-state["heading"])>1e-5:
                obj.rotation_euler.z = state["heading"]
            for key in ("type", "speed", "acceleration", "lane", "turn", "waiting_time", "state", "admitted"):
                if obj.get(key) != state[key]:
                    obj[key] = state[key]
