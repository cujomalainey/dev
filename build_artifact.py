# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing classes that wrap artifact downloads."""

import os
import shutil
import subprocess
import tempfile

import artifact_info
import common_util
import gsutil_util
import log_util


_AU_BASE = 'au'
_NTON_DIR_SUFFIX = '_nton'
_MTON_DIR_SUFFIX = '_mton'

############ Actual filenames of artifacts in Google Storage ############

AU_SUITE_FILE = 'au_control.tar.bz2'
AUTOTEST_FILE = 'autotest.tar'
AUTOTEST_COMPRESSED_FILE = 'autotest.tar.bz2'
DEBUG_SYMBOLS_FILE = 'debug.tgz'
FIRMWARE_FILE = 'firmware_from_source.tar.bz2'
IMAGE_FILE = 'image.zip'
ROOT_UPDATE_FILE = 'update.gz'
STATEFUL_UPDATE_FILE = 'stateful.tgz'
TEST_IMAGE_FILE = 'chromiumos_test_image.bin'
TEST_SUITES_FILE = 'test_suites.tar.bz2'

_build_artifact_locks = common_util.LockDict()


class ArtifactDownloadError(Exception):
  """Error used to signify an issue processing an artifact."""
  pass


class BuildArtifact(log_util.Loggable):
  """Wrapper around an artifact to download from gsutil.

  The purpose of this class is to download objects from Google Storage
  and install them to a local directory. There are two main functions, one to
  download/prepare the artifacts in to a temporary staging area and the second
  to stage it into its final destination.

  Class members:
    archive_url = archive_url
    name: Name given for artifact -- either a regexp or name of the artifact in
          gs. If a regexp, is modified to actual name before call to _Download.
    build: The version of the build i.e. R26-2342.0.0.
    marker_name: Name used to define the lock marker for the artifacts to
                 prevent it from being re-downloaded. By default based on name
                 but can be overriden by children.
    staging_dir: directory for the artifact reserved for staging. Cleaned
                 up after staging.
    tmp_stage_path: Path used in staging_dir for placing artifact.
    install_dir: The final location where the artifact should be staged to.
    single_name: If True the name given should only match one item. Note, if not
                 True, self.name will become a list of items returned.
  """
  def __init__(self, install_dir, archive_url, name, build):
    """Args:
      install_dir: Where to install the artifact.
      archive_url: The Google Storage path to find the artifact.
      name: Identifying name to be used to find/store the artifact.
      build: The name of the build e.g. board/release.
    """
    super(BuildArtifact, self).__init__()

    # In-memory lock to keep the devserver from colliding with itself while
    # attempting to stage the same artifact.
    self._process_lock = None

    self.archive_url = archive_url
    self.name = name
    self.build = build

    self.marker_name = '.' + self._SanitizeName(name)

    self.staging_dir = tempfile.mkdtemp(prefix='Devserver%s' % (
        type(self).__name__))
    self.tmp_stage_path = None

    self.install_dir = install_dir

    self.single_name = True

  @staticmethod
  def _SanitizeName(name):
    """Sanitizes name to be used for creating a file on the filesystem.

    '.','/' and '*' have special meaning in FS lingo. Replace them with words.
    """
    return name.replace('*', 'STAR').replace('.', 'DOT').replace('/', 'SLASH')

  def _ArtifactStaged(self):
    """Returns True if artifact is already staged."""
    return os.path.exists(os.path.join(self.install_dir, self.marker_name))

  def _MarkArtifactStaged(self):
    """Marks the artifact as staged."""
    with open(os.path.join(self.install_dir, self.marker_name), 'w') as f:
      f.write('')

  def _WaitForArtifactToExist(self, timeout):
    """Waits for artifact to exist and sets self.name to appropriate name."""
    names = gsutil_util.GetGSNamesWithWait(
        self.name, self.archive_url, str(self), single_item=self.single_name,
        timeout=timeout)
    if not names:
      raise ArtifactDownloadError('Could not find %s in Google Storage' %
                                  self.name)

    if self.single_name:
      if len(names) > 1:
        raise ArtifactDownloadError('Too many artifacts match %s' % self.name)

      self.name = names[0]
    else:
      self.name = names

  def _Download(self):
    """Downloads artifact from Google Storage to a local staging directory."""
    self.tmp_stage_path = os.path.join(self.staging_dir, self.name)
    gs_path = '/'.join([self.archive_url, self.name])
    gsutil_util.DownloadFromGS(gs_path, self.tmp_stage_path)

  def _Stage(self):
    """Stages the artifact from the tmp directory to the final path."""
    install_path = os.path.join(self.install_dir, self.name)
    shutil.move(self.tmp_stage_path, install_path)

  def Process(self, no_wait):
    """Main call point to all artifacts. Downloads and Stages artifact.

    Downloads and Stages artifact from Google Storage to the install directory
    specified in the constructor. It multi-thread safe and does not overwrite
    the artifact if it's already been downloaded or being downloaded. After
    processing, leaves behind a marker to indicate to future invocations that
    the artifact has already been staged based on the name of the artifact.

    Do not override as it modifies important private variables, ensures thread
    safety, and maintains cache semantics.

    Note: this may be a blocking call when the artifact is already in the
    process of being staged.

    Args:
      no_wait: If True, don't block waiting for artifact to exist if we fail to
               immediately find it.

    Raises:
      ArtifactDownloadError: If the artifact fails to download from Google
                             Storage for any reason or that the regexp
                             defined by name is not specific enough.
    """
    if not self._process_lock:
      self._process_lock = _build_artifact_locks.lock(
          os.path.join(self.install_dir, self.name))

    with self._process_lock:
      common_util.MkDirP(self.install_dir)
      if not self._ArtifactStaged():
        # If the artifact should already have been uploaded, don't waste
        # cycles waiting around for it to exist.
        timeout = 1 if no_wait else 10
        self._WaitForArtifactToExist(timeout)
        self._Download()
        self._Stage()
        self._MarkArtifactStaged()
      else:
        self._Log('%s is already staged.', self)

  def __del__(self):
    shutil.rmtree(self.staging_dir)

  def __str__(self):
    """String representation for the download."""
    return '->'.join(['%s/%s' % (self.archive_url, self.name),
                     self.staging_dir, self.install_dir])


class AUTestPayloadBuildArtifact(BuildArtifact):
  """Wrapper for AUTest delta payloads which need additional setup."""
  def _Stage(self):
    super(AUTestPayloadBuildArtifact, self)._Stage()

    # Rename to update.gz.
    install_path = os.path.join(self.install_dir, self.name)
    new_install_path = os.path.join(self.install_dir, ROOT_UPDATE_FILE)
    shutil.move(install_path, new_install_path)


# TODO(sosa): Change callers to make this artifact more sane.
class DeltaPayloadsArtifact(BuildArtifact):
  """Delta payloads from the archive_url.

  This artifact is super strange. It custom handles directories and
  pulls in all delta payloads. We can't specify exactly what we want
  because unlike other artifacts, this one does not conform to something a
  client might know. The client doesn't know the version of n-1 or whether it
  was even generated.
  """
  def __init__(self, *args):
    super(DeltaPayloadsArtifact, self).__init__(*args)
    self.single_name = False # Expect multiple deltas
    nton_name = 'chromeos_%s%s' % (self.build, self.name)
    mton_name = 'chromeos_(?!%s)%s' % (self.build, self.name)
    nton_install_dir = os.path.join(self.install_dir, _AU_BASE,
                                    self.build + _NTON_DIR_SUFFIX)
    mton_install_dir = os.path.join(self.install_dir, _AU_BASE,
                                   self.build + _MTON_DIR_SUFFIX)
    self._sub_artifacts = [
        AUTestPayloadBuildArtifact(mton_install_dir, self.archive_url,
                                   mton_name, self.build),
        AUTestPayloadBuildArtifact(nton_install_dir, self.archive_url,
                                   nton_name, self.build)]

  def _Download(self):
    """With sub-artifacts we do everything in _Stage()."""
    pass

  def _Stage(self):
    """Process each sub-artifact. Only error out if none can be found."""
    for artifact in self._sub_artifacts:
      try:
        artifact.Process(no_wait=True)
        # Setup symlink so that AU will work for this payload.
        os.symlink(
            os.path.join(os.pardir, os.pardir, STATEFUL_UPDATE_FILE),
            os.path.join(artifact.install_dir, STATEFUL_UPDATE_FILE))
      except ArtifactDownloadError as e:
        self._Log('Could not process %s: %s', artifact, e)


class BundledBuildArtifact(BuildArtifact):
  """A single build artifact bundle e.g. zip file or tar file."""
  def __init__(self, install_dir, archive_url, name, build,
               files_to_extract=None, exclude=None):
    """Takes BuildArtifacts are with two additional args.

    Additional args:
        files_to_extract: A list of files to extract. If set to None, extract
                          all files.
        exclude: A list of files to exclude. If None, no files are excluded.
    """
    super(BundledBuildArtifact, self).__init__(install_dir, archive_url, name,
                                               build)
    self._files_to_extract = files_to_extract
    self._exclude = exclude

    # We modify the marker so that it is unique to what was staged.
    if files_to_extract:
      self.marker_name = self._SanitizeName(
          '_'.join(['.' + self.name] + files_to_extract))

  def _Extract(self):
    """Extracts the bundle into install_dir. Must be overridden.

    If set, uses files_to_extract to only extract those items. If set, use
    exclude to exclude specific files.
    """
    raise NotImplementedError()

  def _Stage(self):
    self._Extract()


class TarballBuildArtifact(BundledBuildArtifact):
  """Artifact for tar and tarball files."""

  def _Extract(self):
    """Extracts a tarball using tar.

    Detects whether the tarball is compressed or not based on the file
    extension and extracts the tarball into the install_path.
    """
    try:
      common_util.ExtractTarball(self.tmp_stage_path, self.install_dir,
                                 files_to_extract=self._files_to_extract,
                                 excluded_files=self._exclude)
    except common_util.CommonUtilError as e:
      raise ArtifactDownloadError(str(e))


class AutotestTarballBuildArtifact(TarballBuildArtifact):
  """Wrapper around the autotest tarball to download from gsutil."""

  def _Stage(self):
    """Extracts the tarball into the install path excluding test suites."""
    super(AutotestTarballBuildArtifact, self)._Stage()

    # Deal with older autotest packages that may not be bundled.
    autotest_dir = os.path.join(self.install_dir, 'autotest')
    autotest_pkgs_dir = os.path.join(autotest_dir, 'packages')
    if not os.path.exists(autotest_pkgs_dir):
      os.makedirs(autotest_pkgs_dir)

    if not os.path.exists(os.path.join(autotest_pkgs_dir, 'packages.checksum')):
      cmd = ['autotest/utils/packager.py', 'upload', '--repository',
             autotest_pkgs_dir, '--all']
      try:
        subprocess.check_call(cmd, cwd=self.staging_dir)
      except subprocess.CalledProcessError, e:
        raise ArtifactDownloadError(
            'Failed to create autotest packages!:\n%s' % e)
    else:
      self._Log('Using pre-generated packages from autotest')


class ZipfileBuildArtifact(BundledBuildArtifact):
  """A downloadable artifact that is a zipfile."""

  def _Extract(self):
    """Extracts files into the install path."""
    # Unzip is weird. It expects its args before any excepts and expects its
    # excepts in a list following the -x.
    cmd = ['unzip', '-o', self.tmp_stage_path, '-d', self.install_dir]
    if self._files_to_extract:
      cmd.extend(self._files_to_extract)

    if self._exclude:
      cmd.append('-x')
      cmd.extend(self._exclude)

    try:
      subprocess.check_call(cmd)
    except subprocess.CalledProcessError, e:
      raise ArtifactDownloadError(
          'An error occurred when attempting to unzip %s:\n%s' %
          (self.tmp_stage_path, e))


class ImplDescription(object):
  """Data wrapper that describes an artifact's implementation."""
  def __init__(self, artifact_class, name, *additional_args):
    """Constructor:

    Args:
      artifact_class: BuildArtifact class to use for the artifact.
      name: name to use to identify artifact (see BuildArtifact.name)
      additional_args: If sub-class uses additional args, these are passed
                       through to them.
    """
    self.artifact_class = artifact_class
    self.name = name
    self.additional_args = additional_args


# Maps artifact names to their implementation description.
# Please note, it is good practice to use constants for these names if you're
# going to re-use the names ANYWHERE else in the devserver code.
ARTIFACT_IMPLEMENTATION_MAP = {
  artifact_info.FULL_PAYLOAD:
      ImplDescription(AUTestPayloadBuildArtifact, '.*_full_.*'),
  artifact_info.DELTA_PAYLOADS:
      ImplDescription(DeltaPayloadsArtifact, '.*_delta_.*'),
  artifact_info.STATEFUL_PAYLOAD:
      ImplDescription(BuildArtifact, STATEFUL_UPDATE_FILE),

  artifact_info.BASE_IMAGE:
      ImplDescription(ZipfileBuildArtifact, IMAGE_FILE,
                      ['chromiumos_base_image.bin']),
  artifact_info.RECOVERY_IMAGE:
      ImplDescription(ZipfileBuildArtifact, IMAGE_FILE, ['recovery_image.bin']),
  artifact_info.TEST_IMAGE:
      ImplDescription(ZipfileBuildArtifact, IMAGE_FILE, [TEST_IMAGE_FILE]),

  artifact_info.AUTOTEST:
      ImplDescription(AutotestTarballBuildArtifact, AUTOTEST_FILE, None,
                      ['autotest/test_suites']),
  artifact_info.TEST_SUITES:
      ImplDescription(TarballBuildArtifact, TEST_SUITES_FILE),
  artifact_info.AU_SUITE:
      ImplDescription(AutotestTarballBuildArtifact, AU_SUITE_FILE),

  artifact_info.FIRMWARE:
      ImplDescription(BuildArtifact, FIRMWARE_FILE),
  artifact_info.SYMBOLS:
      ImplDescription(TarballBuildArtifact, DEBUG_SYMBOLS_FILE,
                      ['debug/breakpad']),
}


class ArtifactFactory(object):
  """A factory class that generates build artifacts from artifact names."""

  def __init__(self, staging_dir, archive_url, artifact_names, build):
    """Initalizes the member variables for the factory.

    Args:
      staging_dir: the dir into which to stage the artifacts.
      archive_url: the Google Storage url of the bucket where the debug
                   symbols for the desired build are stored.
      artifact_names: List of artifact names to stage.
      build: The name of the build.
    """
    self.staging_dir = staging_dir
    self.archive_url = archive_url
    self.artifact_names = artifact_names
    self.build = build

  @staticmethod
  def _GetDescriptionComponents(artifact_name):
    """Returns a tuple of for BuildArtifact class, name, and additional args."""
    description = ARTIFACT_IMPLEMENTATION_MAP[artifact_name]
    return (description.artifact_class, description.name,
            description.additional_args)

  def _Artifacts(self, artifact_names):
    """Returns an iterable of BuildArtifacts from |artifact_names|."""
    artifacts = []
    for artifact_name in artifact_names:
      artifact_class, path, args = self._GetDescriptionComponents(
          artifact_name)
      artifacts.append(artifact_class(self.staging_dir, self.archive_url, path,
                                      self.build, *args))

    return artifacts

  def RequiredArtifacts(self):
    """Returns an iterable of BuildArtifacts for the factory's artifacts."""
    return self._Artifacts(self.artifact_names)

  def OptionalArtifacts(self):
    """Returns an iterable of BuildArtifacts that should be cached."""
    optional_names = set()
    for artifact_name, optional_list in (
        artifact_info.REQUESTED_TO_OPTIONAL_MAP.iteritems()):
      # We are already downloading it.
      if artifact_name in self.artifact_names:
        optional_names = optional_names.union(optional_list)

    return self._Artifacts(optional_names - set(self.artifact_names))
