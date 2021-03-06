#!/bin/bash
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

revbump_ebuild() {
  # Revbump an ebuild file. It has the version number in its name,
  # and furthermore, it's a symlink to another ebuild file.

  # Find a symlink named *.ebuild, should be only one.
  EBUILD=$(find . -name "*.ebuild" -type l)
  # Remove the extension
  F=${EBUILD%.ebuild}
  # Get the numeric suffix after the 'r'.
  # If $F == ./coreboot-private-files-hatch-0.0.1-r30
  # then we want '30'.
  # We need to reverse the string because cut only supports cutting specific
  # fields from the start a string (you can't say N-1, N-2 in general) and
  # we need the last field.
  REVISION=$(echo "${F}" | rev | cut -d- -f 1 | cut -dr -f 1 | rev)
  # Increment
  NEWREV=$((REVISION + 1))
  # Replace e.g. 'r30' with 'r31' in the file name
  NEWEBUILD="${EBUILD/r${REVISION}.ebuild/r${NEWREV}.ebuild}"
  # Rename
  git mv "${EBUILD}" "${NEWEBUILD}"
}
