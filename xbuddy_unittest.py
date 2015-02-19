#!/usr/bin/python2

# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for xbuddy.py."""

from __future__ import print_function

import os
import shutil
import tempfile
import time
import unittest

import mox

import gsutil_util
import xbuddy

#pylint: disable=W0212

GS_ALTERNATE_DIR = 'gs://chromeos-alternate-archive/'


class xBuddyTest(mox.MoxTestBase):
  """Regression tests for xbuddy."""
  def setUp(self):
    mox.MoxTestBase.setUp(self)

    self.static_image_dir = tempfile.mkdtemp('xbuddy_unittest_static')

    self.mock_xb = xbuddy.XBuddy(
        True,
        static_dir=self.static_image_dir
    )
    self.images_dir = tempfile.mkdtemp('xbuddy_unittest_images')
    self.mock_xb.images_dir = self.images_dir

  def tearDown(self):
    """Removes testing files."""
    shutil.rmtree(self.static_image_dir)
    shutil.rmtree(self.images_dir)

  def testParseBoolean(self):
    """Check that some common True/False strings are handled."""
    self.assertEqual(xbuddy.XBuddy.ParseBoolean(None), False)
    self.assertEqual(xbuddy.XBuddy.ParseBoolean('false'), False)
    self.assertEqual(xbuddy.XBuddy.ParseBoolean('bs'), False)
    self.assertEqual(xbuddy.XBuddy.ParseBoolean('true'), True)
    self.assertEqual(xbuddy.XBuddy.ParseBoolean('y'), True)

  def testLookupOfficial(self):
    """Basic test of _LookupOfficial. Checks that a given suffix is handled."""
    self.mox.StubOutWithMock(gsutil_util, 'GSUtilRun')
    gsutil_util.GSUtilRun(mox.IgnoreArg(),
                          mox.IgnoreArg()).AndReturn('v')
    expected = 'b-s/v'
    self.mox.ReplayAll()
    self.assertEqual(self.mock_xb._LookupOfficial('b', '-s'), expected)
    self.mox.VerifyAll()

  def testLookupChannel(self):
    """Basic test of _LookupChannel. Checks that a given suffix is handled."""
    self.mox.StubOutWithMock(gsutil_util, 'GetLatestVersionFromGSDir')
    mock_data1 = '4100.68.0'
    gsutil_util.GetLatestVersionFromGSDir(
        mox.IgnoreArg(), with_release=False).AndReturn(mock_data1)
    mock_data2 = 'R28-4100.68.0'
    gsutil_util.GetLatestVersionFromGSDir(mox.IgnoreArg()).AndReturn(mock_data2)
    self.mox.ReplayAll()
    expected = 'b-release/R28-4100.68.0'
    self.assertEqual(self.mock_xb._LookupChannel('b'),
                     expected)
    self.mox.VerifyAll()

  def testLookupAlias(self):
    """Tests _LookupAlias, including keyword substitution."""
    alias = 'foobar'
    path = 'remote/BOARD/VERSION/test'
    self.mox.StubOutWithMock(self.mock_xb.config, 'get')
    self.mock_xb.config.get(mox.IgnoreArg(), alias).AndReturn(path)
    self.mox.ReplayAll()
    self.assertEqual('remote/parrot/1.2.3/test',
                     self.mock_xb._LookupAlias(alias, 'parrot', '1.2.3'))

  def testResolveVersionToBuildId_Official(self):
    """Check _ResolveVersionToBuildId recognizes aliases for official builds."""
    board = 'b'

    # aliases that should be redirected to LookupOfficial

    self.mox.StubOutWithMock(self.mock_xb, '_LookupOfficial')
    self.mock_xb._LookupOfficial(board, image_dir=None)
    self.mock_xb._LookupOfficial(board,
                                 image_dir=GS_ALTERNATE_DIR)
    self.mock_xb._LookupOfficial(board, 'paladin', image_dir=None)
    self.mock_xb._LookupOfficial(board, 'paladin',
                                 image_dir=GS_ALTERNATE_DIR)

    self.mox.ReplayAll()
    version = 'latest-official'
    self.mock_xb._ResolveVersionToBuildId(board, version)
    self.mock_xb._ResolveVersionToBuildId(board, version,
                                          image_dir=GS_ALTERNATE_DIR)
    version = 'latest-official-paladin'
    self.mock_xb._ResolveVersionToBuildId(board, version)
    self.mock_xb._ResolveVersionToBuildId(board, version,
                                          image_dir=GS_ALTERNATE_DIR)
    self.mox.VerifyAll()

  def testResolveVersionToBuildId_Channel(self):
    """Check _ResolveVersionToBuildId recognizes aliases for channels."""
    board = 'b'

    # aliases that should be redirected to LookupChannel
    self.mox.StubOutWithMock(self.mock_xb, '_LookupChannel')
    self.mock_xb._LookupChannel(board, image_dir=None)
    self.mock_xb._LookupChannel(board, image_dir=GS_ALTERNATE_DIR)
    self.mock_xb._LookupChannel(board, 'dev', image_dir=None)
    self.mock_xb._LookupChannel(board, 'dev', image_dir=GS_ALTERNATE_DIR)

    self.mox.ReplayAll()
    version = 'latest'
    self.mock_xb._ResolveVersionToBuildId(board, version)
    self.mock_xb._ResolveVersionToBuildId(board, version,
                                          image_dir=GS_ALTERNATE_DIR)
    version = 'latest-dev'
    self.mock_xb._ResolveVersionToBuildId(board, version)
    self.mock_xb._ResolveVersionToBuildId(board, version,
                                          image_dir=GS_ALTERNATE_DIR)
    self.mox.VerifyAll()

  def testBasicInterpretPath(self):
    """Basic checks for splitting a path"""
    path = 'parrot/R27-2455.0.0/test'
    expected = ('test', 'parrot', 'R27-2455.0.0', True)
    self.assertEqual(self.mock_xb._InterpretPath(path=path), expected)

    path = 'parrot/R27-2455.0.0/full_payload'
    expected = ('full_payload', 'parrot', 'R27-2455.0.0', True)
    self.assertEqual(self.mock_xb._InterpretPath(path=path), expected)

    path = 'parrot/R27-2455.0.0'
    expected = ('ANY', 'parrot', 'R27-2455.0.0', True)
    self.assertEqual(self.mock_xb._InterpretPath(path=path), expected)

    path = 'remote/parrot/R27-2455.0.0'
    expected = ('test', 'parrot', 'R27-2455.0.0', False)
    self.assertEqual(self.mock_xb._InterpretPath(path=path), expected)

    path = 'local/parrot/R27-2455.0.0'
    expected = ('ANY', 'parrot', 'R27-2455.0.0', True)
    self.assertEqual(self.mock_xb._InterpretPath(path=path), expected)

    path = ''
    expected = ('ANY', None, 'latest', True)
    self.assertEqual(self.mock_xb._InterpretPath(path=path), expected)

    path = 'local'
    expected = ('ANY', None, 'latest', True)
    self.assertEqual(self.mock_xb._InterpretPath(path=path), expected)

    path = 'local/parrot/latest/ANY'
    expected = ('ANY', 'parrot', 'latest', True)
    self.assertEqual(self.mock_xb._InterpretPath(path=path), expected)

  def testInterpretPathWithDefaults(self):
    """Test path splitting with default board/version."""
    path = ''
    expected = ('ANY', 'parrot', 'latest', True)
    self.assertEqual(expected, self.mock_xb._InterpretPath(
        path=path, default_board='parrot'))

    path = ''
    expected = ('ANY', None, '1.2.3', True)
    self.assertEqual(expected, self.mock_xb._InterpretPath(
        path=path, default_version='1.2.3'))

    path = ''
    expected = ('ANY', 'parrot', '1.2.3', True)
    self.assertEqual(expected, self.mock_xb._InterpretPath(
        path=path, default_board='parrot', default_version='1.2.3'))

    path = '1.2.3'
    expected = ('ANY', None, '1.2.3', True)
    self.assertEqual(expected, self.mock_xb._InterpretPath(
        path=path, default_version='1.2.3'))

    path = 'latest'
    expected = ('ANY', None, 'latest', True)
    self.assertEqual(expected, self.mock_xb._InterpretPath(
        path=path, default_version='1.2.3'))

    path = '1.2.3'
    expected = ('ANY', 'parrot', '1.2.3', True)
    self.assertEqual(expected, self.mock_xb._InterpretPath(
        path=path, default_board='parrot', default_version='1.2.3'))

    path = 'parrot'
    expected = ('ANY', 'parrot', '1.2.3', True)
    self.assertEqual(expected, self.mock_xb._InterpretPath(
        path=path, default_version='1.2.3'))

  def testTimestampsAndList(self):
    """Creation and listing of builds according to their timestamps."""
    # make 3 different timestamp files
    b_id11 = 'b1/v1'
    b_id12 = 'b1/v2'
    b_id23 = 'b2/v3'
    xbuddy.Timestamp.UpdateTimestamp(self.mock_xb._timestamp_folder, b_id11)
    time.sleep(0.05)
    xbuddy.Timestamp.UpdateTimestamp(self.mock_xb._timestamp_folder, b_id12)
    time.sleep(0.05)
    xbuddy.Timestamp.UpdateTimestamp(self.mock_xb._timestamp_folder, b_id23)

    # reference second one again
    time.sleep(0.05)
    xbuddy.Timestamp.UpdateTimestamp(self.mock_xb._timestamp_folder, b_id12)

    # check that list returns the same 3 things, in last referenced order
    result = self.mock_xb._ListBuildTimes()
    self.assertEqual(result[0][0], b_id12)
    self.assertEqual(result[1][0], b_id23)
    self.assertEqual(result[2][0], b_id11)

  def testSyncRegistry(self):
    # check that there are no builds initially
    result = self.mock_xb._ListBuildTimes()
    self.assertEqual(len(result), 0)

    # set up the dummy build/images directory with images
    boards = ['a', 'b']
    versions = ['v1', 'v2']
    for b in boards:
      os.makedirs(os.path.join(self.mock_xb.images_dir, b))
      for v in versions:
        os.makedirs(os.path.join(self.mock_xb.images_dir, b, v))

    # Sync and check that they've been added to xBuddy's registry
    self.mock_xb._SyncRegistryWithBuildImages()
    result = self.mock_xb._ListBuildTimes()
    self.assertEqual(len(result), 4)

  ############### Public Methods
  def testXBuddyCaching(self):
    """Caching & replacement of timestamp files."""
    path_a = ('remote', 'a', 'R0', 'test')
    path_b = ('remote', 'b', 'R0', 'test')
    self.mox.StubOutWithMock(gsutil_util, 'GSUtilRun')
    self.mox.StubOutWithMock(self.mock_xb, '_Download')
    self.mox.StubOutWithMock(self.mock_xb, '_Download')
    for _ in range(8):
      self.mock_xb._Download(mox.IsA(str), mox.In(mox.IsA(str)))

    # All non-release urls are invalid so we can meet expectations.
    gsutil_util.GSUtilRun(mox.Not(mox.StrContains('-release')),
                          None).MultipleTimes().AndRaise(
                              gsutil_util.GSUtilError('bad url'))
    gsutil_util.GSUtilRun(mox.StrContains('-release'), None).MultipleTimes()

    self.mox.ReplayAll()

    # requires default capacity
    self.assertEqual(self.mock_xb.Capacity(), '5')

    # Get 6 different images: a,b,c,d,e,f
    images = ['a', 'b', 'c', 'd', 'e', 'f']
    for c in images:
      self.mock_xb.Get(('remote', c, 'R0', 'test'))
      time.sleep(0.05)

    # check that b,c,d,e,f are still stored
    result = self.mock_xb._ListBuildTimes()
    self.assertEqual(len(result), 5)

    # Flip the list to get reverse chronological order
    images.reverse()
    for i in range(5):
      self.assertEqual(result[i][0], '%s-release/R0' % images[i])

    # Get b,a
    self.mock_xb.Get(path_b)
    time.sleep(0.05)
    self.mock_xb.Get(path_a)
    time.sleep(0.05)

    # check that d,e,f,b,a are still stored
    result = self.mock_xb._ListBuildTimes()
    self.assertEqual(len(result), 5)
    images_expected = ['a', 'b', 'f', 'e', 'd']
    for i in range(5):
      self.assertEqual(result[i][0], '%s-release/R0' % images_expected[i])

    self.mox.VerifyAll()


if __name__ == '__main__':
  unittest.main()
