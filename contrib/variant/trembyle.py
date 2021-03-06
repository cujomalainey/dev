# -*- coding: utf-8 -*-
"""Define steps, package names, and directories for creating a Trembyle variant

Copyright 2020 The Chromium OS Authors. All rights reserved.
Use of this source code is governed by a BSD-style license that can be
found in the LICENSE file.
"""

from __future__ import print_function
import step_names

# Name of the baseboard
base = 'zork'

# List of steps (named in step_names.py) to run in sequence to create
# the new variant of the baseboard
step_list = [
    step_names.PROJECT_CONFIG,
    step_names.CB_VARIANT,
    step_names.CB_CONFIG,
    step_names.CRAS_CONFIG,
    step_names.EC_IMAGE,
    step_names.EC_BUILDALL,
    step_names.EMERGE,
    step_names.UPLOAD,
    step_names.CALC_CQ_DEPEND,
    step_names.ADD_CQ_DEPEND,
    step_names.RE_UPLOAD,
    step_names.CLEAN_UP]

# Base directory for coreboot
coreboot_dir = 'third_party/coreboot-zork'

# Base directory for coreboot configs (None=use default)
cb_config_dir = 'overlays/overlay-zork/sys-boot/coreboot-zork/files/configs'

# Package name for FSP
fsp = None

# Package name for the fitimage (None, because Zork doesn't use FIT)
fitimage_pkg = None

# Directory for fitimage (None, because Zork doesn't use FIT)
fitimage_dir = None

# Explanation of gen_fit_image command (None, because Zork doesn't use FIT)
fitimage_cmd = None

# List of packages to cros_workon
workon_pkgs = ['coreboot-zork', 'chromeos-ec', 'chromeos-config-bsp-zork-private']

# The emerge command
emerge_cmd = 'emerge-zork'

# List of packages to emerge
emerge_pkgs = [
    'coreboot-zork', 'vboot_reference',
    'chromeos-ec', 'chromeos-config-bsp-zork-private',
    'chromeos-config', 'chromeos-config-bsp',
    'coreboot-private-files', 'chromeos-bootimage']

# List of packages to cros_workon to build the project config
config_workon_pkgs = ['chromeos-config', 'chromeos-config-bsp-zork-private']

# List of packages to emerge to build the project config
config_emerge_pkgs = [
    'chromeos-config-bsp', 'chromeos-config',
    'chromeos-config-bsp-zork-private']

# Directory for the private yaml file
private_yaml_dir = '~/trunk/src/private-overlays/overlay-zork-private/'\
    'chromeos-base/chromeos-config-bsp-zork-private'

# List of commits that will be uploaded with `repo upload`
repo_upload_list = [
    step_names.CB_VARIANT, step_names.CB_CONFIG,
    step_names.CRAS_CONFIG, step_names.EC_IMAGE, step_names.ADD_PRIV_YAML]

# List of commits that will be pushed to review.coreboot.org
coreboot_push_list = None

# List of steps that depend on other steps, and what those are.
# This list gets used for setting up Cq-Depend on the uploaded CLs.
depends = {
    step_names.CB_CONFIG: [step_names.CB_VARIANT],
    step_names.ADD_PRIV_YAML: [
        step_names.CB_CONFIG, step_names.CRAS_CONFIG,
        step_names.EC_IMAGE],
}
