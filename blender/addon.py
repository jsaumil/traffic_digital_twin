"""Optional Blender sidebar registration, used by launch.py or from Python Console."""
import bpy

bl_info={"name":"Traffic Signal Digital Twin","blender":(4,2,0),"category":"3D View","version":(1,0,0)}


class TRAFFIC_OT_connect(bpy.types.Operator):
    bl_idname="traffic.connect"
    bl_label="Connect traffic twin"

    def execute(self,context):
        from blender.traffic_controller import start
        try:
            start(context.scene.get("traffic_endpoint","ws://127.0.0.1:8875/ws"))
        except (KeyError,ValueError) as exc:
            self.report({'ERROR'},f"Build the traffic scene first: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


class TRAFFIC_OT_disconnect(bpy.types.Operator):
    bl_idname="traffic.disconnect"
    bl_label="Disconnect"

    def execute(self,context):
        from blender.traffic_controller import stop
        stop()
        return {'FINISHED'}


class TRAFFIC_PT_panel(bpy.types.Panel):
    bl_label="Traffic Digital Twin"
    bl_idname="TRAFFIC_PT_panel"
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category="Traffic Twin"

    def draw(self,context):
        self.layout.label(text="LIVE" if context.scene.get("traffic_connected") else "OFFLINE")
        self.layout.label(text=context.scene.get("traffic_phase","Waiting for scene"))
        self.layout.operator("traffic.connect")
        self.layout.operator("traffic.disconnect")


CLASSES=(TRAFFIC_OT_connect,TRAFFIC_OT_disconnect,TRAFFIC_PT_panel)


def register():
    for cls in CLASSES:
        if not hasattr(bpy.types,cls.__name__):
            bpy.utils.register_class(cls)


def unregister():
    from blender.traffic_controller import stop
    stop()
    for cls in reversed(CLASSES):
        if hasattr(bpy.types,cls.__name__):
            bpy.utils.unregister_class(cls)
