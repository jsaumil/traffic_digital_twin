"""blender --background --factory-startup --python tests/blender_integration.py"""
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import bpy
from blender.scene_builder import build_scene
from blender import traffic_controller
from communication.client import WebSocketClient


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}';url=f'ws://127.0.0.1:{port}/ws'
    process=None;controller=None;control=None;result={}
    def server():
        return subprocess.Popen([str(ROOT/'.venv/bin/python'),'run_simulation.py','--port',str(port)],cwd=ROOT,
                                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    def wait(predicate,timeout=10):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if controller:controller.tick()  # All bpy operations remain on this main thread.
            try:
                if predicate():return
            except OSError:pass
            time.sleep(.03)
        raise AssertionError('Traffic Blender integration timed out')
    def health():
        with urlopen(base+'/api/health',timeout=.4) as response:return json.load(response)
    def command(action,parameters=None):
        control.send({'type':'command','request_id':action,'action':action,**({'parameters':parameters} if parameters else {})})
        while True:
            message=control.receive()
            if message['type']=='error':raise AssertionError(message)
            if message['type']=='ack':return message['sequence']
    try:
        process=server();wait(lambda:health()['ok'])
        original=bpy.context.scene;names=set(obj.name for obj in original.objects)
        scene=build_scene();count=len(scene.objects);build_scene()
        assert len(scene.objects)==count and names<={obj.name for obj in original.objects}
        result['repeatable_scene_preserves_existing']=True
        controller=traffic_controller.start(url);wait(lambda:controller.last_state is not None)
        control=WebSocketClient(url)
        initial=tuple(bpy.data.objects['TR.veh_000001'].location)
        command('parameters',{'simulation_speed':5,'green_ns':5,'green_ew':25})
        command('start')
        wait(lambda:math.dist(initial,bpy.data.objects['TR.veh_000001'].location)>.5)
        result['external_simulation_moves_blender_vehicles']=True
        paused_seq=command('pause');wait(lambda:scene.get('traffic_sequence')==paused_seq)
        pose=tuple(bpy.data.objects['TR.veh_000001'].location);timer=scene['traffic_time']
        time.sleep(.25);controller.tick()
        assert tuple(bpy.data.objects['TR.veh_000001'].location)==pose and scene['traffic_time']==timer
        result['pause_freezes_vehicles_and_signal_timers']=True
        command('resume')
        wait(lambda:scene.get('traffic_phase')=='E_GREEN')
        assert bpy.data.objects['TR.signal.E.GREEN']['active']
        assert bpy.data.objects['TR.signal.N.RED']['active']
        assert not bpy.data.objects['TR.signal.N.GREEN']['active']
        result['edited_phase_timings_drive_actual_lamps']=True
        seq=command('reset');wait(lambda:scene.get('traffic_sequence')==seq)
        assert scene['traffic_time']==0 and math.dist(initial,bpy.data.objects['TR.veh_000001'].location)<1e-5
        assert scene['traffic_phase']=='N_GREEN'
        result['reset_restores_signal_phase_and_entity_mapping']=True
        bpy.data.objects.remove(bpy.data.objects['TR.veh_000001'],do_unlink=True)
        seq=command('parameters',{'simulation_speed':2});wait(lambda:scene.get('traffic_sequence')==seq)
        assert bpy.data.objects.get('TR.veh_000001') is not None
        result['missing_vehicle_recovers']=True
        wait(lambda:health()['blender_connected'])
        old_session=scene['traffic_session']
        control.close();control=None;process.terminate();process.wait(timeout=8)
        wait(lambda:not scene.get('traffic_connected'))
        assert 'OFFLINE' in bpy.data.objects['TR.text.connection'].data.body
        process=server();wait(lambda:scene.get('traffic_connected') and scene.get('traffic_session')!=old_session)
        result['websocket_disconnect_and_new_session_reconnect']=True
        (ROOT/'artifacts').mkdir(exist_ok=True)
        (ROOT/'artifacts/blender_integration.json').write_text(json.dumps(result,indent=2))
        print('TRAFFIC_BLENDER_INTEGRATION_PASS '+json.dumps(result),flush=True)
    finally:
        if control:control.close()
        traffic_controller.stop()
        if process and process.poll() is None:process.terminate();process.wait(timeout=8)


if __name__=='__main__':
    try:main()
    except Exception:
        import traceback,os
        traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)
