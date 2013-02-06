# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Applying a Chrome OS update payload.

This module is used internally by the main Payload class for applying an update
payload. The interface for invoking the applier is as follows:

  applier = PayloadApplier(payload)
  applier.Run(...)

"""

import array
import bz2
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

import common
from error import PayloadError


#
# Helper functions.
#
def _VerifySha256(file_obj, expected_hash, name, max_length=-1):
  """Verifies the SHA256 hash of a file.

  Args:
    file_obj: file object to read
    expected_hash: the hash digest we expect to be getting
    name: name string of this hash, for error reporting
    max_length: maximum length of data to read/hash (optional)
  Raises:
    PayloadError if file hash fails to verify.

  """
  # pylint: disable=E1101
  hasher = hashlib.sha256()
  block_length = 1024 * 1024
  if max_length < 0:
    max_length = sys.maxint

  while max_length != 0:
    read_length = min(max_length, block_length)
    data = file_obj.read(read_length)
    if not data:
      break
    max_length -= len(data)
    hasher.update(data)

  actual_hash = hasher.digest()
  if actual_hash != expected_hash:
    raise PayloadError('%s hash (%s) not as expected (%s)' %
                       (name, actual_hash.encode('hex'),
                        expected_hash.encode('hex')))


def _ReadExtents(file_obj, extents, block_size, max_length=-1):
  """Reads data from file as defined by extent sequence.

  This tries to be efficient by not copying data as it is read in chunks.

  Args:
    file_obj: file object
    extents: sequence of block extents (offset and length)
    block_size: size of each block
    max_length: maximum length to read (optional)
  Returns:
    A character array containing the concatenated read data.

  """
  data = array.array('c')
  for ex in extents:
    if max_length == 0:
      break
    file_obj.seek(ex.start_block * block_size)
    read_length = ex.num_blocks * block_size
    if max_length > 0:
      read_length = min(max_length, read_length)
      max_length -= read_length
    data.fromfile(file_obj, read_length)
  return data


def _WriteExtents(file_obj, data, extents, block_size, base_name):
  """Write data to file as defined by extent sequence.

  This tries to be efficient by not copy data as it is written in chunks.

  Args:
    file_obj: file object
    data: data to write
    extents: sequence of block extents (offset and length)
    block_size: size of each block
    base_name: name string of extent block for error reporting
  Raises:
    PayloadError when things don't add up.

  """
  data_offset = 0
  data_length = len(data)
  for ex, ex_name in common.ExtentIter(extents, base_name):
    if data_offset == data_length:
      raise PayloadError('%s: more write extents than data' % ex_name)
    write_length = min(data_length - data_offset, ex.num_blocks * block_size)
    file_obj.seek(ex.start_block * block_size)
    data_view = buffer(data, data_offset, write_length)
    file_obj.write(data_view)
    data_offset += write_length

  if data_offset < data_length:
    raise PayloadError('%s: more data than write extents' % base_name)


#
# Payload application.
#
class PayloadApplier(object):
  """Applying an update payload.

  This is a short-lived object whose purpose is to isolate the logic used for
  applying an update payload.

  """

  def __init__(self, payload):
    assert payload.is_init, 'uninitialized update payload'
    self.payload = payload
    self.block_size = payload.manifest.block_size

  def _ApplyReplaceOperation(self, op, op_name, out_data, part_file, part_size):
    """Applies a REPLACE{,_BZ} operation.

    Args:
      op: the operation object
      op_name: name string for error reporting
      out_data: the data to be written
      part_file: the partition file object
      part_size: the size of the partition
    Raises:
      PayloadError if something goes wrong.

    """
    block_size = self.block_size
    data_length = len(out_data)

    # Decompress data if needed.
    if op.type == common.OpType.REPLACE_BZ:
      out_data = bz2.decompress(out_data)
      data_length = len(out_data)

    # Write data to blocks specified in dst extents.
    data_start = 0
    for ex, ex_name in common.ExtentIter(op.dst_extents,
                                         '%s.dst_extents' % op_name):
      start_block = ex.start_block
      num_blocks = ex.num_blocks
      count = num_blocks * block_size

      # Make sure it's not a fake (signature) operation.
      if start_block != common.PSEUDO_EXTENT_MARKER:
        data_end = data_start + count

        # Make sure we're not running past partition boundary.
        if (start_block + num_blocks) * block_size > part_size:
          raise PayloadError(
              '%s: extent (%s) exceeds partition size (%d)' %
              (ex_name, common.FormatExtent(ex, block_size),
               part_size))

        # Make sure that we have enough data to write.
        if data_end >= data_length + block_size:
          raise PayloadError(
              '%s: more dst blocks than data (even with padding)')

        # Pad with zeros if necessary.
        if data_end > data_length:
          padding = data_end - data_length
          out_data += '\0' * padding

        self.payload.payload_file.seek(start_block * block_size)
        part_file.seek(start_block * block_size)
        part_file.write(out_data[data_start:data_end])

      data_start += count

    # Make sure we wrote all data.
    if data_start < data_length:
      raise PayloadError('%s: wrote fewer bytes (%d) than expected (%d)' %
                         (op_name, data_start, data_length))

  def _ApplyMoveOperation(self, op, op_name, part_file):
    """Applies a MOVE operation.

    Args:
      op: the operation object
      op_name: name string for error reporting
      part_file: the partition file object
    Raises:
      PayloadError if something goes wrong.

    """
    block_size = self.block_size

    # Gather input raw data from src extents.
    in_data = _ReadExtents(part_file, op.src_extents, block_size)

    # Dump extracted data to dst extents.
    _WriteExtents(part_file, in_data, op.dst_extents, block_size,
                  '%s.dst_extents' % op_name)

  def _ApplyBsdiffOperation(self, op, op_name, patch_data, part_file):
    """Applies a BSDIFF operation.

    Args:
      op: the operation object
      op_name: name string for error reporting
      patch_data: the binary patch content
      part_file: the partition file object
    Raises:
      PayloadError if something goes wrong.

    """
    block_size = self.block_size

    # Gather input raw data and write to a temp file.
    in_data = _ReadExtents(part_file, op.src_extents, block_size,
                           max_length=op.src_length)
    with tempfile.NamedTemporaryFile(delete=False) as in_file:
      in_file_name = in_file.name
      in_file.write(in_data)

    # Dump patch data to file.
    with tempfile.NamedTemporaryFile(delete=False) as patch_file:
      patch_file_name = patch_file.name
      patch_file.write(patch_data)

    # Allocate tepmorary output file.
    with tempfile.NamedTemporaryFile(delete=False) as out_file:
      out_file_name = out_file.name

    # Invoke bspatch.
    bspatch_cmd = ['bspatch', in_file_name, out_file_name, patch_file_name]
    subprocess.check_call(bspatch_cmd)

    # Read output.
    with open(out_file_name, 'rb') as out_file:
      out_data = out_file.read()
      if len(out_data) != op.dst_length:
        raise PayloadError(
            '%s: actual patched data length (%d) not as expected (%d)' %
            (op_name, len(out_data), op.dst_length))

    # Write output back to partition, with padding.
    unaligned_out_len = len(out_data) % block_size
    if unaligned_out_len:
      out_data += '\0' * (block_size - unaligned_out_len)
    _WriteExtents(part_file, out_data, op.dst_extents, block_size,
                  '%s.dst_extents' % op_name)

    # Delete all temporary files.
    os.remove(in_file_name)
    os.remove(out_file_name)
    os.remove(patch_file_name)

  def _ApplyOperations(self, operations, base_name, part_file, part_size):
    """Applies a sequence of update operations to a partition.

    This assumes an in-place update semantics, namely all reads are performed
    first, then the data is processed and written back to the same file.

    Args:
      operations: the sequence of operations
      base_name: the name of the operation sequence
      part_file: the partition file object, open for reading/writing
      part_size: the partition size
    Raises:
      PayloadError if anything goes wrong while processing the payload.

    """
    for op, op_name in common.OperationIter(operations, base_name):
      # Read data blob.
      data = self.payload.ReadDataBlob(op.data_offset, op.data_length)

      if op.type in (common.OpType.REPLACE, common.OpType.REPLACE_BZ):
        self._ApplyReplaceOperation(op, op_name, data, part_file, part_size)
      elif op.type == common.OpType.MOVE:
        self._ApplyMoveOperation(op, op_name, part_file)
      elif op.type == common.OpType.BSDIFF:
        self._ApplyBsdiffOperation(op, op_name, data, part_file)
      else:
        raise PayloadError('%s: unknown operation type (%d)' %
                           (op_name, op.type))

  def _ApplyToPartition(self, operations, part_name, base_name,
                        dst_part_file_name, dst_part_info,
                        src_part_file_name=None, src_part_info=None):
    """Applies an update to a partition.

    Args:
      operations: the sequence of update operations to apply
      part_name: the name of the partition, for error reporting
      base_name: the name of the operation sequence
      dst_part_file_name: file name to write partition data to
      dst_part_info: size and expected hash of dest partition
      src_part_file_name: file name of source partition (optional)
      src_part_info: size and expected hash of source partition (optional)
    Raises:
      PayloadError if anything goes wrong with the update.

    """
    # Do we have a source partition?
    if src_part_file_name:
      # Verify the source partition.
      with open(src_part_file_name, 'rb') as src_part_file:
        _VerifySha256(src_part_file, src_part_info.hash, part_name)

      # Copy the src partition to the dst one.
      shutil.copyfile(src_part_file_name, dst_part_file_name)
    else:
      # Preallocate the dst partition file.
      subprocess.check_call(
          ['fallocate', '-l', str(dst_part_info.size), dst_part_file_name])

    # Apply operations.
    with open(dst_part_file_name, 'r+b') as dst_part_file:
      self._ApplyOperations(operations, base_name, dst_part_file,
                            dst_part_info.size)

    # Verify the resulting partition.
    with open(dst_part_file_name, 'rb') as dst_part_file:
      _VerifySha256(dst_part_file, dst_part_info.hash, part_name)

  def Run(self, dst_kernel_part, dst_rootfs_part, src_kernel_part=None,
          src_rootfs_part=None):
    """Applier entry point, invoking all update operations.

    Args:
      dst_kernel_part: name of dest kernel partition file
      dst_rootfs_part: name of dest rootfs partition file
      src_kernel_part: name of source kernel partition file (optional)
      src_rootfs_part: name of source rootfs partition file (optional)
    Raises:
      PayloadError if payload application failed.

    """
    self.payload.ResetFile()

    # Make sure the arguments are sane and match the payload.
    if not (dst_kernel_part and dst_rootfs_part):
      raise PayloadError('missing dst {kernel,rootfs} partitions')

    if not (src_kernel_part or src_rootfs_part):
      if not self.payload.IsFull():
        raise PayloadError('trying to apply a non-full update without src '
                           '{kernel,rootfs} partitions')
    elif src_kernel_part and src_rootfs_part:
      if not self.payload.IsDelta():
        raise PayloadError('trying to apply a non-delta update onto src '
                           '{kernel,rootfs} partitions')
    else:
      raise PayloadError('not all src partitions provided')

    # Apply update to rootfs.
    self._ApplyToPartition(
        self.payload.manifest.install_operations, 'rootfs',
        'install_operations', dst_rootfs_part,
        self.payload.manifest.new_rootfs_info, src_rootfs_part,
        self.payload.manifest.old_rootfs_info)

    # Apply update to kernel update.
    self._ApplyToPartition(
        self.payload.manifest.kernel_install_operations, 'kernel',
        'kernel_install_operations', dst_kernel_part,
        self.payload.manifest.new_kernel_info, src_kernel_part,
        self.payload.manifest.old_kernel_info)