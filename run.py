"""Start server, Blender and browser. Run using this project's virtual environment."""
import argparse
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import webbrowser

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8875)
    parser.add_argument('--blender',default=shutil.which('blender'))
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if not args.blender:parser.error('Blender not found; use --blender /path/to/blender')
    if not 1024<=args.port<=65535:parser.error('Port must be 1024..65535')
    def interrupted(*_):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    try:
        with socket.socket() as probe:probe.bind(('127.0.0.1',args.port))
    except OSError:parser.error('Port busy. Stop the current server or select --port.')
    children=[]
    try:
        server=subprocess.Popen([sys.executable,'run_simulation.py','--port',str(args.port)],cwd=ROOT)
        children.append(server);base=f'http://127.0.0.1:{args.port}'
        deadline=time.monotonic()+8
        while True:
            if server.poll() is not None:raise RuntimeError('Server exited; inspect its error above')
            try:
                with urlopen(base+'/api/health',timeout=.3):break
            except OSError:
                if time.monotonic()>deadline:raise RuntimeError('Server startup timed out')
                time.sleep(.1)
        saved=ROOT/'artifacts/traffic_twin.blend'
        command=[args.blender]+([str(saved)] if saved.exists() else [])
        command+=['--python',str(ROOT/'blender/launch.py'),'--','--url',f'ws://127.0.0.1:{args.port}/ws']
        if not saved.exists():command+=['--save',str(saved)]
        client=subprocess.Popen(command,cwd=ROOT);children.append(client)
        if not args.no_browser:webbrowser.open(base)
        print(f'Traffic twin: {base}\nClick Start. Ctrl+C shuts down the processes launched here.',flush=True)
        while server.poll() is None and client.poll() is None:time.sleep(.2)
        if server.poll() is not None and server.returncode:raise RuntimeError('Traffic server failed')
    except KeyboardInterrupt:pass
    except (OSError,RuntimeError) as exc:
        print(f'Traffic launch failed: {exc}',file=sys.stderr);return 1
    finally:
        for child in reversed(children):
            if child.poll() is None:child.terminate()
        for child in reversed(children):
            try:child.wait(timeout=8)
            except subprocess.TimeoutExpired:child.kill();child.wait()
    return 0


if __name__=='__main__':raise SystemExit(main())
