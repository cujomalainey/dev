# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities."""

from __future__ import print_function

import os

def encode_to_ascii(val):
    """Return the ascii-encoded version of |val|."""
    if not val:
        return val
    return val.encode('ascii', 'ignore')


def clean_git_title(p):
    """Replace certain unicode characters in git commit titles."""
    replacer = {
        'UPSTREAM: ': '',
        'BACKPORT: ': '',
        '\xe2\x80\x9c': '"',
        '\xe2\x80\x98': "'",
        '\xe2\x80\x99': "'",
        '\xef\xbc\x9a': ':',
        '\xe2\x80\x9d': '"',
        '\xe2\x80\xa6': '...',
        '\xe2\x80\x8b': '',
        '\xc2\xb7': ' ',
        '\xd1\x96': 'i',
        '\xc2\xb5': 'm',
        '\xc3\xb8': 'o',
        '\xc3\xbc': 'u',
        '\xc2\xb2': '2',
        '\xc2\xa0': ' ',
        '\xc3\x89': 'E',
        '\xce\x95': 'E',
        '\xd1\x95': 's',
        '\xc3\xa9': 'e',
        '\xc3\xa1': 'a',
        '\xc3\xb6': 'o',
        '\xc4\xa5': 'h',
        '\xc2\xae': '',
        '\xc2\xb6': '[',
        '\xc3\xa4': 'a',
        '\xb4': "'",
        '\x1b': '',
    }
    for k in replacer:
        p = p.replace(k, replacer[k])

    return p


def htmldecode(s):
    """Decode and return an HTML-decoded string |s|."""
    replace_pairs = {
        '&gt;': '>',
        '&lt;': '<',
        '&amp;': '&',
        '&apos;': "'",
        '&#39;': "'",
        '&#34;': '"',
        '&quot;': '"',
    }
    for old in replace_pairs:
        s = s.replace(old, replace_pairs[old])
    return s


def clean_webcontent(cmsg):
    """Cleans a commit message obtained from syzkaller.appspot.com."""
    cmsg = cmsg.replace('net-backports: ', '')
    cmsg = encode_to_ascii(cmsg)
    cmsg = htmldecode(cmsg)
    return cmsg


def interact(qn):
    """Prompt the user for an option and return if response is yes."""
    option = raw_input(qn)
    return option in ['y', 'Y']


def print_report(report):
    """Stub for printing out the report generated by Autotriager."""
    print(report)


def endbanner():
    """Endbanner."""
    print('-' * 30)


def rmfile_if_exists(fname):
    """Remove file if it exists."""
    try:
        os.remove(fname)
    except OSError as _:
        pass


def hit_summary(bbugid, url, cmsg):
    """Generate summary report for Autotriager.

    Generate a summary report with details on matching
    issuetracker and syzweb hits.
    """
    summary = """
    BUG="%s" URL="%s"
    TITLE="%s"
    """ % (bbugid, url, cmsg)
    print(summary)


def commitstr(fixestag):
    """Gives |fixestag| tag from a commit message return the commit message."""
    if '"' in fixestag:
        return fixestag.split('"')[1]
    if '\'' in fixestag:
        return fixestag.split('\'')[1]
    if '(' in fixestag:
        return fixestag.split('(')[1]

    print('Check manually: fixestag=%s' %(repr(fixestag)))
    return None


def incstats(statsobj, s):
    """Increment stats property |s| in |statsobj|."""
    statsobj[s] = statsobj.get(s, 0) + 1


def interesting_keyword_in(body):
    """Returns true if a keyword is present in |body|"""
    keywords = ['overflow', 'oob', 'uaf', 'use after free',
                'use-after-free', 'kasan', 'kmsan', 'syzkaller',
                'reported-by: syzbot',
                ]
    for keyword in keywords:
        if keyword in body.lower():
            return True
    return False


def fixes_stmt(body):
    """Returns the "Fixes: " statement if found in a commit body."""
    for line in body.splitlines():
        if line.startswith('Fixes: '):
            return line
    return None
