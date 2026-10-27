import bpy
from blender.materials import material

COLORS = {"RED": (1,0.025,0.035), "YELLOW": (1,0.53,0.015), "GREEN": (0.02,0.95,0.36)}


class SignalRenderer:
    def __init__(self):
        self.lit = {color: material("Lamp."+color+".ON", value, emission=4) for color,value in COLORS.items()}
        self.dark = {color: material("Lamp."+color+".OFF", tuple(c*0.025 for c in value), roughness=0.3) for color,value in COLORS.items()}
        self.missing = []

    def apply(self, signals):
        self.missing = []
        for approach, active in signals["groups"].items():
            for color in COLORS:
                obj = bpy.data.objects.get(f"TR.signal.{approach}.{color}")
                if obj is None:
                    self.missing.append(f"{approach}.{color}")
                    continue
                desired = self.lit[color] if active == color else self.dark[color]
                if not obj.data.materials or obj.data.materials[0] != desired:
                    obj.data.materials.clear(); obj.data.materials.append(desired)
                obj["active"] = active == color
                obj["signal_group"] = approach
