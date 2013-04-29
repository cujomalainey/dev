# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys

from chromite.lib import terminal

# Output verbosity levels that we support
ERROR = 0
WARNING = 1
NOTICE = 2
INFO = 3
DEBUG = 4

class Output:
  """Output class for Chrome OS.

  This class handles output of progress and other useful information
  to the user. It provides for simple verbosity level control and can
  output nothing but errors at verbosity zero.

  The idea is that modules set up an Output object early in their years and pass
  it around to other modules that need it. This keeps the output under control
  of a single class.

  TODO(sjg): Merge / join with Chromite libraries

  Public properties:
    verbose: Verbosity level: 0=silent, 1=progress, 3=full, 4=debug
  """
  def __init__(self, verbose=WARNING, stdout=sys.stdout):
    """Initialize a new output object.

    Args:
      verbose: Verbosity level (0-4).
      stdout: File to use for stdout.
    """
    self.verbose = verbose
    self._progress = ''          # Our last progress message
    self._color = terminal.Color()
    self._stdout = stdout

    # TODO(sjg): Move this into Chromite libraries when we have them
    self.stdout_is_tty = hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()

  def __enter__(self):
    return self

  def __exit__(self, unused1, unused2, unused3):
    """Clean up and remove any progress message."""
    self.ClearProgress()
    return False

  def UserIsPresent(self):
    """This returns True if it is likely that a user is present.

    Sometimes we want to prompt the user, but if no one is there then this
    is a waste of time, and may lock a script which should otherwise fail.

    Returns:
      True if it thinks the user is there, and False otherwise
    """
    return self.stdout_is_tty and self.verbose > 0

  def ClearProgress(self):
    """Clear any active progress message on the terminal."""
    if self.verbose > 0 and self.stdout_is_tty:
      self._stdout.write('\r%s\r' % (" " * len (self._progress)))
      self._stdout.flush()

  def Progress(self, msg, warning=False, trailer='...'):
    """Display progress information.

    Args:
      msg: Message to display.
      warning: True if this is a warning."""
    self.ClearProgress()
    if self.verbose > 0:
      self._progress = msg + trailer
      if self.stdout_is_tty:
        col = self._color.YELLOW if warning else self._color.GREEN
        self._stdout.write('\r' + self._color.Color(col, self._progress))
        self._stdout.flush()
      else:
        self._stdout.write(self._progress + '\n')

  def _Output(self, level, msg, color=None):
    """Output a message to the terminal.

    Args:
      level: Verbosity level for this message. It will only be displayed if
          this as high as the currently selected level.
      msg; Message to display.
      error: True if this is an error message, else False.
    """
    if self.verbose >= level:
      self.ClearProgress()
      if color:
        msg = self._color.Color(color, msg)
      self._stdout.write(msg + '\n')

  def DoOutput(self, level, msg):
    """Output a message to the terminal.

    Args:
      level: Verbosity level for this message. It will only be displayed if
          this as high as the currently selected level.
      msg; Message to display.
    """
    self._Output(level, msg)

  def Error(self, msg):
    """Display an error message

    Args:
      msg; Message to display.
    """
    self._Output(0, msg, self._color.RED)

  def Warning(self, msg):
    """Display a warning message

    Args:
      msg; Message to display.
    """
    self._Output(1, msg, self._color.YELLOW)

  def Notice(self, msg):
    """Display an important infomation message

    Args:
      msg; Message to display.
    """
    self._Output(2, msg)

  def Info(self, msg):
    """Display an infomation message

    Args:
      msg; Message to display.
    """
    self._Output(3, msg)

  def Debug(self, msg):
    """Display a debug message

    Args:
      msg; Message to display.
    """
    self._Output(4, msg)

  def UserOutput(self, msg):
    """Display a message regardless of the current output level.

    This is used when the output was specifically requested by the user.
    Args:
      msg; Message to display.
    """
    self._Output(0, msg)
