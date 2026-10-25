#!/usr/bin/env bash
set -euo pipefail

M8_TIMER="jason-os-source-monitor-staging.timer"
M9_TIMER="jason-os-source-monitor-staging-batch.timer"

usage() {
  echo "Usage:"
  echo "  $0 --confirm-cutover"
  echo "  $0 --confirm-rollback"
}

enabled() {
  systemctl is-enabled --quiet "$1" 2>/dev/null
}

active() {
  systemctl is-active --quiet "$1" 2>/dev/null
}

require_disabled_inactive() {
  local unit="$1"

  if enabled "$unit"; then
    echo "REFUSED: $unit must be disabled"
    exit 64
  fi

  if active "$unit"; then
    echo "REFUSED: $unit must be inactive"
    exit 64
  fi
}

require_enabled_active() {
  local unit="$1"

  if ! enabled "$unit"; then
    echo "REFUSED: $unit must be enabled"
    exit 64
  fi

  if ! active "$unit"; then
    echo "REFUSED: $unit must be active"
    exit 64
  fi
}

cutover() {
  require_enabled_active "$M8_TIMER"
  require_disabled_inactive "$M9_TIMER"

  echo "CUTOVER STEP 1: disable M8"
  systemctl disable --now "$M8_TIMER"

  require_disabled_inactive "$M8_TIMER"

  echo "CUTOVER STEP 2: enable M9"

  if ! systemctl enable --now "$M9_TIMER"; then
    echo "CUTOVER FAILED: restoring M8"
    systemctl disable --now "$M9_TIMER" || true
    systemctl enable --now "$M8_TIMER"
    require_enabled_active "$M8_TIMER"
    require_disabled_inactive "$M9_TIMER"
    echo "ROLLBACK_AFTER_FAILED_CUTOVER: PASS"
    exit 1
  fi

  require_disabled_inactive "$M8_TIMER"
  require_enabled_active "$M9_TIMER"

  echo "m8_timer_enabled=false"
  echo "m8_timer_active=false"
  echo "m9_timer_enabled=true"
  echo "m9_timer_active=true"
  echo "STATUS: M9_SCHEDULER_CUTOVER_COMPLETE"
}

rollback() {
  require_disabled_inactive "$M8_TIMER"
  require_enabled_active "$M9_TIMER"

  echo "ROLLBACK STEP 1: disable M9"
  systemctl disable --now "$M9_TIMER"

  require_disabled_inactive "$M9_TIMER"

  echo "ROLLBACK STEP 2: enable M8"
  systemctl enable --now "$M8_TIMER"

  require_enabled_active "$M8_TIMER"
  require_disabled_inactive "$M9_TIMER"

  echo "m8_timer_enabled=true"
  echo "m8_timer_active=true"
  echo "m9_timer_enabled=false"
  echo "m9_timer_active=false"
  echo "STATUS: M9_SCHEDULER_ROLLBACK_COMPLETE"
}

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  echo "REFUSED: cutover must run as root"
  exit 64
fi

if [ "$#" -ne 1 ]; then
  usage
  exit 64
fi

case "$1" in
  --confirm-cutover)
    cutover
    ;;
  --confirm-rollback)
    rollback
    ;;
  *)
    usage
    exit 64
    ;;
esac
