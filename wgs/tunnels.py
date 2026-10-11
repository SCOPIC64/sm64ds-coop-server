"""Own and restart the two outbound tunnels with the WGS server process."""
import json
from pathlib import Path
import re
import subprocess
import threading


class Tunnels:
    def __init__(self, tools, manifest, lobby_port):
        self.tools = Path(tools)
        self.manifest = Path(manifest)
        self.lobby_port = lobby_port
        for name in ('playit.exe', 'cloudflared.exe', 'playit-secret.txt'):
            if not (self.tools / name).is_file():
                raise RuntimeError('Missing private tunnel file: ' + name)
        self.stopping = threading.Event()
        self.processes = {}
        self.streams = {}
        self.worker = threading.Thread(target=self._run, daemon=True)

    def publish(self, url=None):
        temporary = self.manifest.with_suffix('.tmp')
        temporary.write_text(json.dumps({'lobby_url': url}), encoding='utf-8')
        temporary.replace(self.manifest)

    def start(self):
        self.publish()
        self.worker.start()

    def _spawn(self, name):
        if name == 'playit':
            args = [str(self.tools/'playit.exe'), '--stdout', '--secret_path', str(self.tools/'playit-secret.txt'), 'start']
        else:
            args = [str(self.tools/'cloudflared.exe'), 'tunnel', '--no-autoupdate', '--protocol', 'http2', '--url', 'http://127.0.0.1:%d' % self.lobby_port]
        previous = self.streams.pop(name, None)
        if previous is not None:
            previous.close()
        log = (self.tools/(name+'.log')).open('wb')
        self.streams[name] = log
        self.processes[name] = subprocess.Popen(args, cwd=self.tools, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

    def _run(self):
        announced = False
        try:
            while not self.stopping.is_set():
                for name in ('playit', 'cloudflared'):
                    process = self.processes.get(name)
                    if process is None or process.poll() is not None:
                        if name == 'cloudflared':
                            self.publish();announced = False
                        self._spawn(name)
                if not announced:
                    text = (self.tools/'cloudflared.log').read_text(encoding='utf-8',errors='replace')
                    match = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', text)
                    if match:
                        self.publish(match[0]);announced=True
                        print('Public lobby tunnel ready; clients discover it automatically.',flush=True)
                self.stopping.wait(2)
        except (OSError, ValueError) as error:
            self.publish()
            print('Tunnel supervisor stopped: %s' % error,flush=True)
        finally:
            self.publish()
            for process in self.processes.values():
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill();process.wait(timeout=3)
            for stream in self.streams.values():
                stream.close()

    def close(self):
        self.stopping.set()
        if self.worker.is_alive():
            self.worker.join(timeout=10)
