from pathlib import Path
import json
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


@pytest.fixture
def server():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    process=subprocess.Popen([sys.executable,'run_simulation.py','--port',str(port)],cwd=ROOT,
                             stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    base=f'http://127.0.0.1:{port}'
    deadline=time.monotonic()+8
    try:
        while True:
            if process.poll() is not None: raise AssertionError('Test server exited')
            try:
                with urlopen(base+'/api/health',timeout=.2) as response:
                    json.load(response)
                break
            except OSError:
                if time.monotonic()>deadline: raise
                time.sleep(.03)
        yield base, f'ws://127.0.0.1:{port}/ws',process
    finally:
        if process.poll() is None:
            process.terminate();process.wait(timeout=8)
