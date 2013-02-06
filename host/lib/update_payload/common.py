# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities for update payload processing."""

import ctypes
import textwrap

from error import PayloadError
import update_metadata_pb2


#
# Constants.
#
PSEUDO_EXTENT_MARKER = ctypes.c_uint64(-1).value


#
# Payload operation types.
#
class OpType(object):
  """Container for operation type constants."""
  _CLASS = update_metadata_pb2.DeltaArchiveManifest.InstallOperation
  # pylint: disable=E1101
  REPLACE = _CLASS.REPLACE
  REPLACE_BZ = _CLASS.REPLACE_BZ
  MOVE = _CLASS.MOVE
  BSDIFF = _CLASS.BSDIFF
  NAMES = {
      REPLACE: 'REPLACE',
      REPLACE_BZ: 'REPLACE_BZ',
      MOVE: 'MOVE',
      BSDIFF: 'BSDIFF',
  }

  def __init__(self):
    pass


#
# Checker and hashed reading of data.
#
def Read(file_obj, length, offset=None, hasher=None):
  """Reads binary data from a file.

  Args:
    file_obj: an open file object
    length: the length of the data to read
    offset: an offset to seek to prior to reading; this is an absolute offset
            from either the beginning (non-negative) or end (negative) of the
            file.  (optional)
    hasher: a hashing object to pass the read data through (optional)
  Returns:
    A string containing the read data.
  Raises:
    PayloadError if a read error occurred or not enough data was read.

  """
  if offset is not None:
    if offset >= 0:
      file_obj.seek(offset)
    else:
      file_obj.seek(offset, 2)

  try:
    data = file_obj.read(length)
  except IOError, e:
    raise PayloadError('error reading from file (%s): %s' % (file_obj.name, e))

  if len(data) != length:
    raise PayloadError(
        'reading from file (%s) too short (%d instead of %d bytes)' %
        (file_obj.name, len(data), length))

  if hasher:
    hasher.update(data)

  return data


#
# Formatting functions.
#
def FormatExtent(ex, block_size=0):
  end_block = ex.start_block + ex.num_blocks
  if block_size:
    return '%d->%d * %d' % (ex.start_block, end_block, block_size)
  else:
    return '%d->%d' % (ex.start_block, end_block)


def FormatSha256(digest):
  """Returns a canonical string representation of a SHA256 digest."""
  return '\n'.join(textwrap.wrap(digest.encode('hex'), 32))


#
# Useful iterators.
#
def _ObjNameIter(items, base_name, reverse=False, name_format_func=None):
  """A generic (item, name) tuple iterators.

  Args:
    items: the sequence of objects to iterate on
    base_name: the base name for all objects
    reverse: whether iteration should be in reverse order
    name_format_func: a function to apply to the name string
  Yields:
    An iterator whose i-th invocation returns (items[i], name), where name ==
    base_name + '[i]' (with a formatting function optionally applied to it).

  """
  idx, inc = (len(items), -1) if reverse else (1, 1)
  for item in items:
    item_name = '%s[%d]' % (base_name, idx)
    if name_format_func:
      item_name = name_format_func(item, item_name)
    yield (item, item_name)
    idx += inc


def _OperationNameFormatter(op, op_name):
  return '%s(%s)' % (op_name, OpType.NAMES.get(op.type, '?'))


def OperationIter(operations, base_name, reverse=False):
  """An (item, name) iterator for update operations."""
  return _ObjNameIter(operations, base_name, reverse=reverse,
                      name_format_func=_OperationNameFormatter)


def ExtentIter(extents, base_name, reverse=False):
  """An (item, name) iterator for operation extents."""
  return _ObjNameIter(extents, base_name, reverse=reverse)


def SignatureIter(sigs, base_name, reverse=False):
  """An (item, name) iterator for signatures."""
  return _ObjNameIter(sigs, base_name, reverse=reverse)