#!/usr/bin/env bash

set -euo pipefail
IFS=$'\n\t'

# Logging functions
function log_error() {
    printf '\e[31mERROR:\e[0m %s\n' "$*" >&2
    exit 1
}

function log_warn() {
    printf '\e[33mWARN:\e[0m %s\n' "$*" >&2
    ((ISSUE++))
}

function log_info() {
    printf '\e[32mINFO:\e[0m %s\n' "$*" >&2
}

function remote_exec() {
    ssh -t "${REMOTE_HOST}" "sh -lc \"set -e;$*\""
}

# Configuration
readonly MOUNT_POINT="/home/steki/addons"
readonly REMOTE_HOST="hassio"

# Check if already mounted
if LANG=C df -h "${MOUNT_POINT}" | grep -q hassio; then
    log_info "Already mounted"
else
    log_info "Mounting sshfs"
    if ! sshfs "${REMOTE_HOST}:/addons" "${MOUNT_POINT}"; then
        log_error "Failed sshfs mount"
    fi
fi

# Clean and deploy
rm -rf "${MOUNT_POINT}/borg-backup" || true
mkdir -p "${MOUNT_POINT}/borg-backup"
cp -a ./* "${MOUNT_POINT}/borg-backup/"
log_info "Deployed source"

# Execute Home Assistant commands
for cmd in \
    "ha addons reload" \
    "ha addons rebuild local_borg-backup" \
    "ha addons restart local_borg-backup"; do
    log_info "Executing: ${cmd}"
    remote_exec "${cmd}"
done

# Wait for restart and show logs
sleep 2
log_info "Showing logs"
remote_exec "ha addons logs local_borg-backup"
