#!/usr/bin/env python2
# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Mock Omaha server"""

from __future__ import print_function

# pylint: disable=cros-logging-import
import argparse
import copy
import json
import logging
import os
import sys
import threading
import traceback

from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, time
from xml.etree import ElementTree


class XMLResponseTemplates(object):
  """XML Templates"""

  RESPONSE_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<response protocol="3.0" server="nebraska">
  <daystart elapsed_days="" elapsed_seconds=""/>
</response>
"""

  APP_TEMPLATE = """
  <app appid="" status="">
  </app>
"""

  PING_RESPONSE = """
    <ping status="ok"/>
  """

  EVENT_RESPONSE = """
    <event status="ok"/>
  """

  UPDATE_CHECK_TEMPLATE = """
    <updatecheck status="ok">
      <urls>
      </urls>
      <manifest version="">
        <actions>
          <action event="update" run=""/>
          <action ChromeOSVersion=""
                  ChromeVersion="1.0.0.0"
                  IsDeltaPayload=""
                  MaxDaysToScatter="14"
                  MetadataSignatureRsa=""
                  MetadataSize=""
                  event="postinstall"/>
        </actions>
        <packages>
          <package fp=""
                   hash_sha256=""
                   name=""
                   required="true"
                   size=""/>
        </packages>
      </manifest>
    </updatecheck>
  """

  UPDATE_CHECK_NO_UPDATE = """
    <updatecheck status="noupdate"/>
  """

  ERROR_NOT_FOUND = "error-unknownApplication"


def VersionCmp(version_a_str, version_b_str):
  """Compare two version strings.

  Currently we only match on major/minor versions.

  Args:
    version_a_str: String representing first version number.
    version_b_str: String representing second version number.

  Returns:
    < 0 if version_a is less than version_b.
    > 0 if version_a is greater than version_b.
    0 if the version numbers are equal.

  Raises:
    ValueError if either version string is not valid.
  """

  try:
    version_a = tuple([int(i) for i in version_a_str.split('.')[0:2]])
    version_b = tuple([int(i) for i in version_b_str.split('.')[0:2]])

    if version_a[0] != version_b[0]:
      return version_a[0] - version_b[0]

    return version_a[1] - version_b[1]

  except (IndexError, ValueError):
    raise ValueError("Not a valid version string")


class Request(object):
  """Request consisting of a list of apps to update/install."""

  APP_TAG = 'app'
  APPID_ATTR = 'appid'
  VERSION_ATTR = 'version'
  DELTA_OKAY_ATTR = 'delta_okay'
  HW_CLASS_ATTR = 'hardware_class'
  UPDATE_CHECK_TAG = 'updatecheck'
  PING_TAG = 'ping'
  EVENT_TAG = 'event'
  EVENT_TYPE_ATTR = 'eventtype'
  EVENT_RESULT_ATTR = 'eventresult'

  def __init__(self, request_str):
    """Initializes a request instance.

    Args:
      request_str: XML-formatted request string.
    """
    self.request_str = request_str

  def ParseRequest(self):
    """Parse an XML request string into a list of app requests.

    An app request can be a no-op, an install request, or an update request, and
    may include a ping and/or event tag. We treat app requests with the update
    tag omitted as no-ops, since the server is not required to return payload
    information. Install requests are signalled by sending app requests along
    with a no-op request for the platform app.

    Returns:
      A list of AppRequest instances.

    Raises:
      ValueError if the request string is not a valid XML request.
    """
    try:
      request_root = ElementTree.fromstring(self.request_str)
    except ElementTree.ParseError as err:
      logging.error("Request string is not valid XML (%s)", str(err))
      raise ValueError

    # TODO(chowes): It would be better to specifically check the platform app.
    # An install is signalled by omitting the update check for the platform
    # app, which can be found based on the presense of a hardware_class tag,
    # which is absent on DLC update and install requests. UE does not currently
    # omit hardware_class for DLCs, so we assume that if we have one appid for
    # which the update_check tag is omitted, it is the platform app and this is
    # an install request. This assumption should be fine since we never mix
    # updates with requests that do not include an update_check tag.
    app_elements = request_root.findall(self.APP_TAG)
    noop_count = len(
        [x for x in app_elements if x.find(self.UPDATE_CHECK_TAG) is None])

    if noop_count > 1 and noop_count < len(app_elements):
      raise ValueError("Client request omits update_check tag for more than "
                       "one, but not all app requests.")

    is_install = noop_count == 1

    app_requests = []
    for app in app_elements:
      appid = app.get(self.APPID_ATTR)
      version = app.get(self.VERSION_ATTR)
      delta_okay = app.get(self.DELTA_OKAY_ATTR) == "true"

      event = app.find(self.EVENT_TAG)
      if event is not None:
        event_type = event.get(self.EVENT_TYPE_ATTR)
        event_result = event.get(self.EVENT_RESULT_ATTR, 0)
      else:
        event_type = None
        event_result = None

      ping = app.find(self.PING_TAG) is not None

      if app.find(self.UPDATE_CHECK_TAG) is not None:
        if is_install:
          request_type = Request.AppRequest.RequestType.INSTALL
        else:
          request_type = Request.AppRequest.RequestType.UPDATE
      else:
        request_type = Request.AppRequest.RequestType.NO_OP

      app_request = Request.AppRequest(
          request_type=request_type,
          appid=appid,
          ping=ping,
          version=version,
          delta_okay=delta_okay,
          event_type=event_type,
          event_result=event_result)

      if not app_request.IsValid():
        raise ValueError("Invalid request: %s", str(app_request))

      app_requests.append(app_request)

    return app_requests

  class AppRequest(object):
    """An app request.

    Can be an update request, install request, or neither if the update check
    tag is omitted (i.e. the platform app when installing a DLC, or when a
    request is only an event), in which case we treat the request as a no-op.
    An app request can also send pings and event result information.
    """

    class RequestType(object):
      """Simple enumeration for encoding request type."""
      INSTALL = 1 # Request installation of a new app.
      UPDATE = 2 # Request update for an existing app.
      NO_OP = 3 # Request does not require a payload response.

    def __init__(self, request_type, appid, ping=False, version=None,
                 delta_okay=None, event_type=None, event_result=None):
      """Initializes a Request.

      Args:
        request_type: install, update, or no-op.
        appid: The requested appid.
        ping: True if the server should respond to a ping.
        version: Current Chrome OS version.
        delta_okay: True if an update request can accept a delta update.
        event_type: Type of event.
        event_result: Event result.

        More on event pings:
        https://github.com/google/omaha/blob/master/doc/ServerProtocolV3.md
      """
      self.request_type = request_type
      self.appid = appid
      self.ping = ping
      self.version = version
      self.delta_okay = delta_okay
      self.event_type = event_type
      self.event_result = event_result

    def __str__(self):
      """Returns a string representation of an AppRequest."""
      if self.request_type == self.RequestType.NO_OP:
        return "{}".format(self.appid)
      elif self.request_type == self.RequestType.INSTALL:
        return "install {} v{}".format(self.appid, self.version)
      elif self.request_type == self.RequestType.UPDATE:
        return "{} update {} from v{}".format(
            "delta" if self.delta_okay else "full", self.appid, self.version)

    def IsValid(self):
      """Returns true if an AppRequest is valid, False otherwise."""
      return None not in (self.request_type, self.appid, self.version)

class Response(object):
  """An update/install response.

  A response to an update or install request consists of an XML-encoded list
  of responses for each appid in the client request. This class takes a list of
  responses for update/install requests and compiles them into a single element
  constituting an aggregate response that can be returned to the client in XML
  format based on the format of an XML response template.
  """

  def __init__(self, request, update_index, install_index, payload_addr):
    """Initialize a reponse from a list of matching apps.

    Args:
      request: Request instance describing client requests.
      update_index: Index of update payloads.
      install_index: Index of install payloads.
      payload_addr: Address of payload server.
    """
    self._request = request
    self._update_index = update_index
    self._install_index = install_index
    self._payload_addr = payload_addr

    curr = datetime.now()
    self._elapsed_days = (curr - datetime(2007, 1, 1)).days
    self._elapsed_seconds = int((
        curr - datetime.combine(curr.date(), time.min)).total_seconds())

  def GetXMLString(self):
    """Generates a response to a set of client requests.

    Given a client request consisting of one or more app requests, generate a
    response to each of these requests and combine them into a single
    XML-formatted response.

    Returns:
      XML-formatted response string consisting of a response to each app request
      in the incoming request from the client.
    """
    try:
      response_xml = ElementTree.fromstring(
          XMLResponseTemplates.RESPONSE_TEMPLATE)
      response_xml.find("daystart").set("elapsed_days", str(self._elapsed_days))
      response_xml.find(
          "daystart").set("elapsed_seconds", str(self._elapsed_seconds))

      for app_request in self._request.ParseRequest():
        logging.debug("Request for appid %s", str(app_request))
        response_xml.append(self.AppResponse(
            app_request,
            self._update_index,
            self._install_index,
            self._payload_addr).Compile())

    except Exception as err:
      logging.error("Failed to compile response (%s)", str(err))
      raise

    return ElementTree.tostring(
        response_xml, encoding='UTF-8', method='xml')

  class AppResponse(object):
    """Response to an app request.

    If the request was an update or install request, the response should include
    a matching app if one was found. Addionally, the response should include
    responses to pings and events as appropriate.
    """

    def __init__(self, app_request, update_index, install_index, payload_addr):
      """Initialize an AppResponse.

      Attributes:
        app_request: AppRequest representing a client request.
        update_index: Index of update payloads.
        install_index: Index of install payloads.
        payload_addr: Address serving payloads.
      """
      _INSTALL_PATH = "/install/"
      _UPDATE_PATH = "/update/"

      self._app_request = app_request
      self._app_data = None
      self._payload_url = None
      self._err_not_found = False

      if self._app_request.request_type == \
          self._app_request.RequestType.INSTALL:
        self._app_data = install_index.Find(self._app_request)
        self._payload_url = payload_addr + _INSTALL_PATH
        self._err_not_found = self._app_data is None
      elif self._app_request.request_type == \
          self._app_request.RequestType.UPDATE:
        self._app_data = update_index.Find(self._app_request)
        self._payload_url = payload_addr + _UPDATE_PATH
        # This differentiates between apps that are not in the index and apps
        # that are available, but do not have an update available. Omaha treats
        # the former as an error, whereas the latter case should result in a
        # response containing a "noupdate" tag.
        self._err_not_found = self._app_data is None and \
            not update_index.Contains(app_request)

      if self._app_data:
        logging.debug("Found matching payload: %s", str(self._app_data))
      elif self._err_not_found:
        logging.debug("No matches for appid %s", self._app_request.appid)
      elif self._app_request.request_type == \
          self._app_request.RequestType.UPDATE:
        logging.debug("No updates available for %s", self._app_request.appid)

    def Compile(self):
      """Compiles an app description into XML format.

      Compile the app description into an ElementTree Element that can be used
      to compile a response to a client request, and ultimately converted into
      XML.

      Returns:
        An ElementTree Element instance describing an update or install payload.
      """
      app_response = ElementTree.fromstring(XMLResponseTemplates.APP_TEMPLATE)
      app_response.set('appid', self._app_request.appid)

      if self._app_request.ping:
        app_response.append(
            ElementTree.fromstring(XMLResponseTemplates.PING_RESPONSE))
      if self._app_request.event_type is not None:
        app_response.append(
            ElementTree.fromstring(XMLResponseTemplates.EVENT_RESPONSE))

      if self._app_data is not None:
        app_response.set('status', 'ok')
        app_response.append(
            ElementTree.fromstring(XMLResponseTemplates.UPDATE_CHECK_TEMPLATE))
        urls = app_response.find('./updatecheck/urls')
        urls.append(
            ElementTree.Element('url', attrib={'codebase': self._payload_url}))
        manifest = app_response.find('./updatecheck/manifest')
        manifest.set('version', self._app_data.version)
        actions = manifest.findall('./actions/action')
        actions[0].set('run', self._app_data.name)
        actions[1].set('ChromeOSVersion', self._app_data.version)
        actions[1].set(
            'IsDeltaPayload', 'true' if self._app_data.is_delta else 'false')
        actions[1].set('MetadataSignatureRsa', self._app_data.metadata_sig)
        actions[1].set('MetadataSize', str(self._app_data.metadata_size))
        package = manifest.find('./packages/package')
        package.set('fp', "1.%s" % self._app_data.sha256_hash)
        package.set('hash_sha256', self._app_data.sha256_hash)
        package.set('name', self._app_data.name)
        package.set('size', str(self._app_data.size))
      elif self._err_not_found:
        app_response.set('status', XMLResponseTemplates.ERROR_NOT_FOUND)
      elif self._app_request.request_type == \
          self._app_request.RequestType.UPDATE:
        app_response.set('status', "ok")
        app_response.append(ElementTree.fromstring(
            XMLResponseTemplates.UPDATE_CHECK_NO_UPDATE))

      return app_response


class AppData(object):
  """Data about an available app.

  Data about an available app that can be either installed or upgraded to. This
  information is compiled into XML format and returned to the client in an app
  tag in the server's response to an update or install request.
  """

  APPID_KEY = 'appid'
  NAME_KEY = 'name'
  IS_DELTA_KEY = 'is_delta'
  SIZE_KEY = 'size'
  METADATA_SIG_KEY = 'metadata_sig'
  METADATA_SIZE_KEY = 'metadata_size'
  VERSION_KEY = 'version'
  SRC_VERSION_KEY = 'source_ver'
  SHA256_HASH_KEY = 'hash_sha256'

  def __init__(self, app_data):
    """Initialize AppData

    Args:
      app_data: Dictionary containing attributes used to init AppData instance.

    Attributes:
      template: Defines the format of an app element in the XML response.
      appid: appid of the requested app.
      name: Filename of requested app on the mock Lorry server.
      is_delta: True iff the payload is a delta update.
      size: Size of the payload.
      metadata_sig: Metadata signature.
      metadata_size: Metadata size.
      sha256_hash: SHA256 hash of the payload encoded in hexadecimal.
      version: ChromeOS version the payload is tied to.
      src_version: Source version for delta updates.
    """
    self.appid = app_data[self.APPID_KEY]
    self.name = app_data[self.NAME_KEY]
    self.version = app_data[self.VERSION_KEY]
    self.is_delta = app_data[self.IS_DELTA_KEY]
    self.src_version = (
        app_data[self.SRC_VERSION_KEY] if self.is_delta else None)
    self.size = app_data[self.SIZE_KEY]
    self.metadata_sig = app_data[self.METADATA_SIG_KEY]
    self.metadata_size = app_data[self.METADATA_SIZE_KEY]
    self.sha256_hash = app_data[self.SHA256_HASH_KEY]
    self.url = None # Determined per-request.

  def __str__(self):
    if self.is_delta:
      return "{} v{}: delta update from base v{}".format(
          self.appid, self.version, self.src_version)
    return "{} v{}: full update/install".format(
        self.appid, self.version)

  def MatchRequest(self, request):
    """Returns true iff the app matches a given client request.

    An app matches a request if the appid matches the requested appid.
    Additionally, if the app describes a delta update payload, the request
    must be able to accept delta payloads, and the source versions must match.
    If the request is not an update, the versions must match.

    Args:
      request: A request object describing a client request.

    Returns:
      True if the app matches the given request, False otherwise.
    """
    # TODO(chowes): We only account for tip/branch versions. We need to be able
    # to handle full version strings as well as developer builds that don't have
    # a "real" final version component.

    if self.appid != request.appid:
      return False

    try:
      if request.request_type == request.RequestType.UPDATE:
        if self.is_delta:
          if not request.delta_okay:
            return False
          if VersionCmp(request.version, self.src_version) != 0:
            return False
        return VersionCmp(request.version, self.version) < 0

      if request.request_type == request.RequestType.INSTALL:
        if self.is_delta:
          return False
        return VersionCmp(request.version, self.version) == 0

      else:
        return False

    except ValueError as err:
      logging.error("Unable to compare version strings (%s)", str(err))
      return False


class AppIndex(object):
  """An index of available app payload information.

  Index of available apps used to generate responses to Omaha requests. The
  index consists of lists of payload information associated with a given appid,
  since we can have multiple payloads for a given app (different versions,
  delta/full payloads). The index is built by scanning a given directory for
  json files that describe the available payloads.
  """

  def __init__(self, directory):
    """Initializes an AppIndex instance.

    Attributes:
      directory: Directory containing metdata and payloads, can be None.
      index: Dictionary of metadata describing payloads for a given appid.
    """
    self._directory = directory
    self._index = {}

  def Scan(self):
    """Invalidates the current cache and scans the directory.

    Clears the cached index and rescans the directory.
    """
    self._index.clear()

    if self._directory is None:
      return

    for f in os.listdir(self._directory):
      if f.endswith('.json'):
        try:
          with open(os.path.join(self._directory, f), 'r') as metafile:
            metadata_str = metafile.read()
            metadata = json.loads(metadata_str)
            app = AppData(metadata)

            if app.appid not in self._index:
              self._index[app.appid] = []
            self._index[app.appid].append(app)
        except (IOError, KeyError, ValueError) as err:
          logging.error("Failed to read app data from %s (%s)", f, str(err))
          raise
        logging.debug("Found app data: %s", str(app))

  def Find(self, request):
    """Search the index for a given appid.

    Searches the index for the payloads matching a client request. Matching is
    based on appid, version, and whether the client is searching for an update
    and can handle delta payloads.

    Args:
      request: AppRequest describing the client request.

    Returns:
      An AppData object describing an available payload matching the client
      request, or None if no matches are found. Prefer delta payloads if the
      client can accept them and if one is available.
    """
    # Find a list of payloads matching the client request.
    matches = [app for app in self._index.get(request.appid, []) if
               app.MatchRequest(request)]

    if not matches:
      return None

    # Find the highest version out of the matching payloads.
    max_version = reduce(
        lambda a, b: a if VersionCmp(a.version, b.version) > 0
        else b, matches).version

    matches = [app for app in matches if app.version == max_version]

    # If the client can handle a delta, prefer to send a delta.
    if request.delta_okay:
      match = next((x for x in matches if x.is_delta), None)
      match = match if match else next(iter(matches), None)
    else:
      match = next(iter(matches), None)

    return copy.copy(match)

  def Contains(self, request):
    """Checks if the AppIndex contains any apps matching a given request appid.

    Checks the index for an appid matching the appid in the given request. This
    is necessary because it allows us to differentiate between the case where we
    have no new versions of an app and the case where we have no information
    about an app at all.

    Args:
      request: Describes the client request.

    Returns:
      True if the index contains any appids matching the appid given in the
      request.
    """
    return request.appid in self._index


class NebraskaHandler(BaseHTTPRequestHandler):
  """HTTP request handler for Omaha requests."""

  def do_POST(self):
    """Responds to XML-formatted Omaha requests."""
    request_len = int(self.headers.getheader('content-length'))
    request_str = self.rfile.read(request_len)
    logging.debug("Received request: %s", request_str)

    request = Request(request_str)

    try:
      response = Response(
          request,
          self.server.owner.update_index,
          self.server.owner.install_index,
          self.server.owner.payload_addr)
      response_str = response.GetXMLString()
    except Exception as err:
      logging.error("Failed to handle request (%s)", str(err))
      traceback.print_exc()
      self.send_error(500, "Failed to handle incoming request")
      return

    self.send_response(200)
    self.send_header('Content-Type', 'application/xml')
    self.end_headers()
    self.wfile.write(response_str)


class NebraskaServer(object):
  """A simple Omaha server instance.

  A simple mock of an Omaha server. Responds to XML-formatted update/install
  requests based on the contents of metadata files in update and install
  directories, respectively. These metadata files are used to configure
  responses to Omaha requests from Update Engine and describe update and install
  payloads provided by another server.
  """

  def __init__(self, payload_addr, update_dir, install_dir, port=0):
    """Initializes a server instance.

    Args:
      payload_addr: Address and port of the payload server.
      update_dir: Directory to index for information about update payloads.
      install_dir: Directory to index for information about install payloads.
      port: Port the server should run on, 0 if the OS should assign a port.

    Attributes:
      update_index: Index of metadata files in the update directory.
      install_index: Index of metadata files in the install directory.
    """
    self._port = port
    self._httpd = None
    self._server_thread = None
    self.payload_addr = payload_addr.strip('/')
    self.update_index = AppIndex(update_dir)
    self.install_index = AppIndex(install_dir)

  def Start(self):
    """Starts a mock Omaha HTTP server."""
    self.update_index.Scan()
    self.install_index.Scan()

    self._httpd = HTTPServer(('', self.Port()), NebraskaHandler)
    self._port = self._httpd.server_port
    self._httpd.owner = self
    self._server_thread = threading.Thread(target=self._httpd.serve_forever)
    self._server_thread.start()

  def Stop(self):
    """Stops the mock Omaha server."""
    self._httpd.shutdown()
    self._server_thread.join()

  def Port(self):
    """Returns the server's port."""
    return self._port


def ParseArguments(argv):
  """Parses command line arguments.

  Args:
    argv: List of commandline arguments.

  Returns:
    Namespace object containing parsed arguments.
  """
  parser = argparse.ArgumentParser(description=__doc__)

  parser.add_argument('--update-payloads', metavar='DIR', default=None,
                      help='Directory containing payloads for updates.',
                      required=False)
  parser.add_argument('--install-payloads', metavar='DIR', default=None,
                      help='Directory containing payloads for installation.',
                      required=False)
  parser.add_argument('--port', metavar='PORT', type=int, default=0,
                      help='Port to run the server on', required=False)
  parser.add_argument('--payload-addr', metavar='URL',
                      help='Base payload URL.',
                      default="http://127.0.0.1:8080")

  return parser.parse_args(argv[1:])


def main(argv):
  logging.basicConfig(level=logging.DEBUG)
  opts = ParseArguments(argv)

  if not opts.update_payloads and not opts.install_payloads:
    logging.error("Need to specify at least one payload directory.")
    return os.EX_USAGE

  nebraska = NebraskaServer(payload_addr=opts.payload_addr,
                            update_dir=opts.update_payloads,
                            install_dir=opts.install_payloads,
                            port=opts.port)

  nebraska.Start()
  logging.info("Running on port %d. Press 'q' to quit.", nebraska.Port())

  try:
    while raw_input() != 'q':
      pass
  except(EOFError, KeyboardInterrupt, SystemExit):
    pass

  logging.info("Exiting...")
  nebraska.Stop()

  return os.EX_OK


if __name__ == "__main__":
  sys.exit(main(sys.argv))