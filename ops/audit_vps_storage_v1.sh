#!/usr/bin/env bash
set -euo pipefail

classify_usage() {
  local used="$1"
  if (( used < 60 )); then
    echo "Healthy"
  elif (( used < 70 )); then
    echo "Observe"
  elif (( used < 80 )); then
    echo "Warning"
  elif (( used <= 85 )); then
    echo "Cleanup required"
  else
    echo "Critical"
  fi
}

echo "============================================================"
echo "Jason OS VPS Storage Audit v1"
echo "READ-ONLY"
echo "============================================================"

root_used="$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}')"
root_free="$(df -hP / | awk 'NR==2 {print $4}')"
root_size="$(df -hP / | awk 'NR==2 {print $2}')"

echo
echo "[ROOT FILESYSTEM]"
echo "size=$root_size"
echo "free=$root_free"
echo "used_percent=${root_used}%"
echo "status=$(classify_usage "$root_used")"

echo
echo "[FILESYSTEMS]"
df -hP

echo
echo "[TOP-LEVEL WORKING AREAS]"
for path in \
  /opt \
  /tmp \
  /var/log \
  /var/lib/docker
do
  if [[ -e "$path" ]]; then
    du -shx "$path" 2>/dev/null || true
  fi
done

echo
echo "[JASON OS DIRECTORIES]"
for path in \
  /opt/ai-knowledge \
  /opt/ai-knowledge-staging \
  /opt/jasonos \
  /opt/infra \
  /opt/personal \
  /tmp/jason-os
do
  if [[ -e "$path" ]]; then
    du -shx "$path" 2>/dev/null || true
  fi
done

echo
echo "[DOCKER STORAGE]"
if command -v docker >/dev/null 2>&1; then
  docker system df || true

  echo
  echo "[DOCKER CONTAINERS]"
  docker ps -a \
    --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Size}}' || true

  echo
  echo "[DOCKER VOLUMES]"
  docker volume ls || true
else
  echo "docker_not_found"
fi

echo
echo "[SYSTEMD JOURNAL]"
if command -v journalctl >/dev/null 2>&1; then
  journalctl --disk-usage || true
else
  echo "journalctl_not_found"
fi

echo
echo "============================================================"
echo "AUDIT COMPLETE - NO CLEANUP OR WRITE ACTION WAS PERFORMED"
echo "============================================================"
