#!/bin/sh

# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This scripts performs update of stateful partition directories useful for
# dev_mode.

# Die on error.
set -e

STATEFUL_DIR="/mnt/stateful_partition"
STATEFUL_IMAGE="$STATEFUL_DIR/stateful.image"
STATEFUL_MOUNT_POINT="/tmp/s"

PING_OMAHA=/opt/google/memento_updater/ping_omaha.sh

# Get image url for stateful image
OMAHA_CHECK_OUTPUT=$($PING_OMAHA --app_version ForcedUpdate 2> /dev/null)
ROOT_UPDATE_URL=$(echo "$OMAHA_CHECK_OUTPUT" | grep '^URL=' | cut -d = -f 2-)
STATEFUL_UPDATE_URL="$(dirname "$ROOT_UPDATE_URL")/stateful.image.gz"

# Prepare directories for update.
rm -rf "$STATEFUL_DIR/var_new" "$STATEFUL_DIR/dev_image_new"

# Prepare and mount new stateful partition.
rm -rf "$STATEFUL_MOUNT_POINT"
mkdir -p "$STATEFUL_MOUNT_POINT"

# Unzip mount and copy the relevant directories.
# Get the update.
eval "wget -O - \"$STATEFUL_UPDATE_URL\"" | gzip -d > $STATEFUL_IMAGE
trap "rm -f \"$STATEFUL_IMAGE\"" EXIT
mount -n -o loop "$STATEFUL_IMAGE" "$STATEFUL_MOUNT_POINT"
if [ -d "$STATEFUL_MOUNT_POINT/var" ] && \
    [ -d "$STATEFUL_MOUNT_POINT/dev_image" ] ; then
  cp -rf "$STATEFUL_MOUNT_POINT/var" "$STATEFUL_DIR/var_new"
  cp -rf "$STATEFUL_MOUNT_POINT/dev_image" "$STATEFUL_DIR/dev_image_new"
  touch "$STATEFUL_DIR/.update_available"
else
  echo "No update available"
fi

umount -n -d "$STATEFUL_MOUNT_POINT"

rm -f "$STATEFUL_IMAGE"

trap - EXIT