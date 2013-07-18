# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module contains constants shared across all other devserver modules."""

#### Google Storage locations and names. ####
# TODO (joyc) move the google storage filenames of artfacts here
GS_IMAGE_DIR = 'gs://chromeos-image-archive'
GS_LATEST_MASTER = GS_IMAGE_DIR + '/%(board)s-%(suffix)s/LATEST-master'
IMAGE_DIR = '%(board)s-%(suffix)s/%(version)s'

GS_RELEASES_DIR = 'gs://chromeos-releases'
GS_CHANNEL_DIR = GS_RELEASES_DIR + '/%(channel)s-channel/%(board)s/'

VERSION_RE = 'R?[-0-9\.]+'

#### Local storage locations and names. ####
AUTOTEST_DIR = 'autotest'
ROOT_UPDATE_FILE = 'update.gz'
IMAGE_FILE = "chromiumos_image.bin"
BASE_IMAGE_FILE = 'chromiumos_base_image.bin'
TEST_IMAGE_FILE = 'chromiumos_test_image.bin'
RECOVERY_IMAGE_FILE = 'recovery_image.bin'