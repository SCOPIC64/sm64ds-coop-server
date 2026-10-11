"""Check the real reverse proxy, blank page and lobby."""
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

base = sys.argv[1].rstrip('/')
with urllib.request.urlopen(base + '/', timeout=10) as response:
    expected = Path(__file__).resolve().parents[1] / 'site/index.html'
    assert response.read() == expected.read_bytes(), 'Root must serve the blank page'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
with urllib.request.urlopen(base + '/port/lobby/health', timeout=10) as response:
    health = json.load(response)
    assert health['ok'] and health['contract_v'] == 4 and health['dial_max'] == 16

def post(verb, body):
    req = urllib.request.Request(base + '/port/lobby/' + verb,
        data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)

# Exercise the deployed configuration without leaving a room behind.
room = post('create', {'v': 4, 'nick': 'deployment-check'})
try:
    assert room.get('room') and room.get('token'), room
finally:
    if room.get('room') and room.get('token'):
        post('leave', {'v': 4, 'room': room['room'], 'token': room['token']})

# Neither deployment configuration nor the source tree is exposed by Caddy.
for path in ('/.env', '/compose.yaml', '/lobby/app/server.py'):
    try:
        urllib.request.urlopen(base + path, timeout=10)
    except urllib.error.HTTPError as error:
        assert error.code == 404, (path, error.code)
    else:
        raise AssertionError('Unexpected public file: ' + path)
print('PASS: blank page, proxy, lobby room lifecycle and private file boundaries')
