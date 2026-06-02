#!/bin/bash

# Allow custom mount point via first argument; fallback to default
MOUNT_POINT="${1:-${BR_OAK_MOUNT:-/oak}}"
REMOTE_PATH="zijiao@sherlock.stanford.edu:/oak/stanford/groups/russpold"
SSH_CONFIG="/tmp/sshfs_config"

echo "[1/3] Unmounting (if exists): $MOUNT_POINT"
fusermount3 -u "$MOUNT_POINT" 2>/dev/null || true

echo "[2/3] Mounting with uid/gid mapping"
uid=$(id -u)
gid=$(id -g)

if [[ ! -f "$SSH_CONFIG" ]]; then
  cat >"$SSH_CONFIG" <<'EOF'
Host sherlock.stanford.edu
  PreferredAuthentications keyboard-interactive,password
  ServerAliveInterval 15
  ServerAliveCountMax 3
EOF
fi

sshfs -F "$SSH_CONFIG" \
  -o reconnect,cache=no,allow_other,default_permissions,uid=$uid,gid=$gid,umask=0022 \
  "$REMOTE_PATH" \
  "$MOUNT_POINT"

echo "[3/3] Verify"
ls -ld "$MOUNT_POINT"
