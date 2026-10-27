"""Optional desktop test: launches a temporary Blender window, then closes it."""
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]


def main():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    process=subprocess.Popen([sys.executable,'run.py','--no-browser','--port',str(port)],cwd=ROOT)
    try:
        deadline=time.monotonic()+35
        while time.monotonic()<deadline:
            if process.poll() is not None:raise AssertionError('Launcher exited before Blender connected')
            try:
                with urlopen(base+'/api/health',timeout=.4) as response:
                    if json.load(response)['blender_connected']:break
            except OSError:pass
            time.sleep(.2)
        else:raise AssertionError('Launched Blender never acknowledged traffic state')
        process.send_signal(signal.SIGINT);assert process.wait(timeout=15)==0
        try:
            with urlopen(base+'/api/health',timeout=.3):raise AssertionError('Server outlived launcher')
        except OSError:pass
        report={'saved_scene_loaded':True,'blender_websocket_ack':True,'owned_process_shutdown':True}
        (ROOT/'artifacts/launcher_smoke.json').write_text(json.dumps(report,indent=2))
        print('TRAFFIC_LAUNCHER_SMOKE_PASS '+json.dumps(report))
    finally:
        if process.poll() is None:process.terminate();process.wait(timeout=15)


if __name__=='__main__':main()
