#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 1 || ! $1 =~ ^[A-Za-z0-9][A-Za-z0-9.-]*$ ]]; then
  echo 'Usage: bash deploy/start-server.sh PUBLIC-RELAY-HOSTNAME' >&2
  exit 2
fi
task_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$task_root"
docker compose version >/dev/null
task_hostname=$1
umask 077
if [[ -f .env ]]; then cp -- .env .env.backup; fi
printf 'SITE_ADDRESS=%s\nRELAY_PUBLIC_ADDR=%s:41234\n' "$task_hostname" "$task_hostname" > .env
docker compose config --quiet
docker compose up -d --build
docker compose ps
echo 'Wait for HTTPS provisioning, then check:'
printf 'curl --fail https://%s/port/lobby/health\n' "$task_hostname"
