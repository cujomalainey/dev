#!/usr/bin/env python3
# -*- coding: utf-8 -*-"
#
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module rebuilding database with metadata about chromeos patches."""

from __future__ import print_function
import re
import subprocess
import MySQLdb
import common


UPSTREAM = re.compile(r'(ANDROID: *|UPSTREAM: *|FROMGIT: *|BACKPORT: *)+(.*)')
CHROMIUM = re.compile(r'(CHROMIUM: *|FROMLIST: *)+(.*)')
CHANGEID = re.compile(r'^( )*Change-Id: [a-zA-Z0-9]*$')


def parse_changeID(chromeos_sha):
    """String searches for Change-Id in a chromeos git commit.

    Returns Change-Id or None if commit doesn't have associated Change-Id
    """
    commit = subprocess.check_output(['git', 'show', \
            chromeos_sha]).decode('utf-8', errors='ignore')

    for line in commit.splitlines():
        if CHANGEID.match(line):
            # removes whitespace prefixing Change-Id
            line = line.lstrip()
            commit_changeID = line[(line.index(' ') + 1):]
            return commit_changeID

    return None


def search_usha(sha, description):
    """Search for upstream SHA.

    If found, return upstream sha associated with this commit sha.
    """

    usha = None
    if not CHROMIUM.match(description):
        desc = subprocess.check_output(['git', 'show',
            '-s', sha]).decode('utf-8', errors='ignore')
        # TODO(hirthanan) change regex to parse entire description not line by line
        for d in desc.splitlines():
            m = common.CHERRYPICK.search(d)
            if not m:
                m = common.STABLE.search(d)
                if not m:
                    m = common.STABLE2.search(d)
            if m:
                # The patch may have been picked multiple times; only record
                # the first entry.
                usha = m.group(2)[:12]
                return usha
    return usha


def update_chrome_table(branch, start, db):
    """Updates the linux chrome commits table.

    Also keep a reference of last parsed SHA so we don't have to index the
        entire commit log on each run.
    Skip commit if it is contained in the linux stable db, add to linux_chrome
    """
    subprocess.run(['git', 'checkout', common.chromeos_branch(branch)])
    subprocess.run(['git', 'pull'])

    subprocess_cmd = ['git', 'log', '--no-merges', '--abbrev=12',
                      '--oneline', '--reverse', '%s..' % start]
    commits = subprocess.check_output(subprocess_cmd).decode('utf-8', errors='ignore')

    c = db.cursor()
    last = None
    for commit in commits.splitlines():
        if commit:
            elem = commit.split(' ', 1)
            sha = elem[0]

            description = elem[1].rstrip('\n')

            ps = subprocess.Popen(['git', 'show', sha], stdout=subprocess.PIPE)
            spid = subprocess.check_output(['git', 'patch-id', '--stable'],
                    stdin=ps.stdout).decode('utf-8', errors='ignore')
            patchid = spid.split(' ', 1)[0]

            # Do nothing if sha is in linux_chrome or linux_stable since we
            #  don't want to track linux_stable sha's that are merged into linux_chrome
            q = """SELECT 1 FROM linux_chrome
                    JOIN linux_stable
                    WHERE linux_chrome.sha = %s OR linux_stable.sha = %s"""
            c.execute(q, [sha, sha])
            found = c.fetchone()
            if found:
                continue

            last = sha

            usha = search_usha(sha, description)

            try:
                q = """INSERT INTO linux_chrome
                        (sha, branch, upstream_sha, patch_id, description)
                        VALUES (%s, %s, %s, %s, %s)"""
                c.execute(q, [sha, branch, usha, patchid, description])
            except MySQLdb.Error as e: # pylint: disable=no-member
                print('Error in insertion into linux_chrome with values: ',
                        [sha, branch, usha, patchid, description], e)
            except UnicodeDecodeError as e:
                print('Failed to INSERT stable sha %s with desciption %s'
                        % (sha, description), e)

    # Update previous fetch database
    if last:
        common.update_previous_fetch(db, common.Kernel.linux_chrome, branch, last)

    db.commit()



if __name__ == '__main__':
    cloudsql_db = MySQLdb.Connect(user='linux_patches_robot', host='127.0.0.1', db='linuxdb')
    common.update_kernel_db(cloudsql_db, common.Kernel.linux_chrome)
    cloudsql_db.close()
