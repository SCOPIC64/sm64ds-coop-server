import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from wgs.tunnels import Tunnels


class TunnelOwnership(unittest.TestCase):
    def test_restart_updates_discovery_and_stop_closes_owned_processes(self):
        with tempfile.TemporaryDirectory() as folder:
            tools=Path(folder)
            for name in ('playit.exe','cloudflared.exe','playit-secret.txt'):
                (tools/name).write_text('isolated test fixture')
            manifest=tools/'tunnel.json';supervisor=Tunnels(tools,manifest,8091)
            created=[];urls=[];cloud_count=0;iterations=0

            class Process:
                def __init__(self,name,number):self.name=name;self.number=number;self.checks=0;self.done=False
                def poll(self):
                    self.checks+=1
                    if self.name=='cloudflared' and self.number==1 and self.checks>=1:self.done=True
                    return 0 if self.done else None
                def terminate(self):self.done=True
                def wait(self,timeout):return 0
                def kill(self):self.done=True

            def spawn(args,**kwargs):
                nonlocal cloud_count
                name=Path(args[0]).stem
                if name=='cloudflared':
                    cloud_count+=1
                    self.assertIn('http://127.0.0.1:8091',args)
                    kwargs['stdout'].write(('https://lobby%d.trycloudflare.com\n'%cloud_count).encode());kwargs['stdout'].flush()
                process=Process(name,cloud_count);created.append(process);return process

            original_publish=supervisor.publish
            def publish(url=None):urls.append(url);original_publish(url)
            def tick(_):
                nonlocal iterations
                iterations+=1
                if iterations==2:supervisor.stopping.set()

            with mock.patch('wgs.tunnels.subprocess.Popen',side_effect=spawn),mock.patch.object(supervisor,'publish',side_effect=publish),mock.patch.object(supervisor.stopping,'wait',side_effect=tick):
                supervisor.start();supervisor.worker.join(timeout=3)
                self.assertFalse(supervisor.worker.is_alive())
                supervisor.close()
            self.assertEqual(cloud_count,2)
            self.assertIn('https://lobby1.trycloudflare.com',urls)
            self.assertIn('https://lobby2.trycloudflare.com',urls)
            self.assertTrue(all(p.done for p in created))
            self.assertIsNone(json.loads(manifest.read_text())['lobby_url'])
