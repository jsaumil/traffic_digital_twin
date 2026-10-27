import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    import bpy
    from blender.scene_builder import SCENE_NAME,build_scene
    from blender import traffic_controller
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",default="ws://127.0.0.1:8875/ws")
    parser.add_argument("--rebuild",action="store_true")
    parser.add_argument("--save",type=Path)
    args=parser.parse_args(sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else [])
    traffic_controller.stop()
    scene=bpy.data.scenes.get(SCENE_NAME)
    if scene is None or args.rebuild:
        scene=build_scene()
    elif bpy.context.window:
        bpy.context.window.scene=scene
    scene["traffic_endpoint"]=args.url
    if args.save:
        args.save.parent.mkdir(parents=True,exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.save.resolve()))
    traffic_controller.start(args.url)
    from blender import addon
    addon.register()
    print("TRAFFIC_TWIN_READY "+args.url,flush=True)


if __name__=="__main__":
    main()
