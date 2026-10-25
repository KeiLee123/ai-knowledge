#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${JASON_REPO_ROOT:-/opt/ai-knowledge-staging}"
SYSTEMD_DIR="${JASON_SYSTEMD_DIR:-/etc/systemd/system}"

SERVICE="jason-os-source-monitor-staging-batch.service"
TIMER="jason-os-source-monitor-staging-batch.timer"

SOURCE_SERVICE="$REPO_ROOT/ops/systemd/$SERVICE"
SOURCE_TIMER="$REPO_ROOT/ops/systemd/$TIMER"

DEST_SERVICE="$SYSTEMD_DIR/$SERVICE"
DEST_TIMER="$SYSTEMD_DIR/$TIMER"

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "REFUSED: installer must run as root"
  exit 64
fi

if [ "$(git -C "$REPO_ROOT" branch --show-current)" != "staging" ]; then
  echo "REFUSED: installer checkout must be on staging branch"
  exit 64
fi

if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
  echo "REFUSED: installer checkout worktree must be clean"
  exit 64
fi

test -f "$SOURCE_SERVICE" || {
  echo "REFUSED: source service unit missing"
  exit 64
}

test -f "$SOURCE_TIMER" || {
  echo "REFUSED: source timer unit missing"
  exit 64
}

if systemctl is-enabled --quiet "$TIMER" 2>/dev/null; then
  echo "REFUSED: M9 batch timer is already enabled"
  exit 64
fi

if systemctl is-active --quiet "$TIMER" 2>/dev/null; then
  echo "REFUSED: M9 batch timer is already active"
  exit 64
fi

install -m 0644 "$SOURCE_SERVICE" "$DEST_SERVICE"
install -m 0644 "$SOURCE_TIMER" "$DEST_TIMER"

systemctl daemon-reload

if systemctl is-enabled --quiet "$TIMER" 2>/dev/null; then
  echo "REFUSED: installer unexpectedly enabled M9 timer"
  exit 65
fi

if systemctl is-active --quiet "$TIMER" 2>/dev/null; then
  echo "REFUSED: installer unexpectedly activated M9 timer"
  exit 65
fi

echo "service_installed=$DEST_SERVICE"
echo "timer_installed=$DEST_TIMER"
echo "service_sha256=$(sha256sum "$DEST_SERVICE" | awk '{print $1}')"
echo "timer_sha256=$(sha256sum "$DEST_TIMER" | awk '{print $1}')"
echo "m9_timer_enabled=false"
echo "m9_timer_active=false"
echo "STATUS: M9_BATCH_UNITS_INSTALLED_NOT_ACTIVATED"
