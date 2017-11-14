#!/usr/bin/python
# Copyright 2017 Scraper Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This program presents the cloud dtatastore status to the fleet.

This is a webserver that reads from cloud datastore and presents the requested
information in json form.

Nodes in the MLab fleet used to use a spreadsheet to determine what data is and
is not safe to delete. Unfortunately, if every scraper just wrote to that
spreadsheet, then we would quickly run out of spreadsheet API quota.  Also, the
spreadsheet is kind of a janky hack for what really should be a key-value store.
The new scraper has its source of truth in a key-value store (Google Cloud
Datastore), and this program has the job of updating the spreadsheet with that
truth.  In a longer term migration, this script and the spreadsheet should both
be eliminated, and the scripts in charge of data deletion should read from a
low-latency source of cloud datastore data.

This program needs to be run on a GCE instance that has access to the Sheets
API.  Sheets API access is not enabled by default for GCE, and it can't be
enabled from the web-based GCE instance creation interface.  Worse, the scopes
that a GCE instance has can't be changed after creation. To create a new GCE
instance named scraper-dev that has access to both cloud APIs and spreadsheet
apis, you could use the following command line:
   gcloud compute instances create scraper-dev \
       --scopes cloud-platform,https://www.googleapis.com/auth/spreadsheets
"""

import argparse
import BaseHTTPServer
import collections
import datetime
import logging
import httplib
import json
import random
import re
import SocketServer
import ssl
import sys
import textwrap
import thread
import threading
import time
import traceback
import urlparse

import apiclient
import dateutil.parser
import prometheus_client
import prometheus_client.core

# pylint: disable=no-name-in-module
from google.cloud import datastore
# pylint: enable=no-name-in-module
from oauth2client.contrib import gce

# Prometheus histogram buckets are web-response-sized by default, with lots of
# sub-second buckets and very few multi-second buckets.  We need to change them
# to rsync-download-sized, with lots of multi-second buckets up to even a
# multi-hour bucket or two.  The precise choice of bucket values below is a
# compromise between exponentially-sized bucket growth and a desire to make
# sure that the bucket sizes are nice round time units.
TIME_BUCKETS = (0.0, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0,
                1800.0, 3600.0, 7200.0, float('inf'))

# The monitoring variables exported by the prometheus_client
# The prometheus_client libraries confuse the linter.
# pylint: disable=no-value-for-parameter
RUNS = prometheus_client.Histogram(
    'spreadsheet_sync_runtime_seconds',
    'How long each sheet sync took',
    buckets=TIME_BUCKETS)
SLEEPS = prometheus_client.Histogram(
    'spreadsheet_sync_sleep_time_seconds',
    'Sleep time between sheet update runs (should be an exp distribution)',
    buckets=TIME_BUCKETS)
# pylint: enable=no-value-for-parameter
SUCCESS = prometheus_client.Counter(
    'spreadsheet_sync_success',
    'How many times has the sheet update succeeded and failed',
    ['message'])
REQUEST_TIMES = prometheus_client.Histogram(
    'request_time_seconds',
    'Running time of web server requests',
    ['message'])  # e.g. json, root, metrics, ...
REQUEST_TIMES_JSON = REQUEST_TIMES.labels(message='json')
REQUEST_TIMES_ROOT_URL = REQUEST_TIMES.labels(message='root_url')
REQUEST_TIMES_COLLECT = REQUEST_TIMES.labels(message='collect')
REQUEST_TIMES_ERROR = REQUEST_TIMES.labels(message='error')

# pylint: disable=no-value-for-parameter
DATASTORE_TIMES = prometheus_client.Histogram(
    'datastore_time_seconds',
    'Running time of datastore requests')


class SyncException(Exception):
    """The exceptions this system raises."""


def parse_args(argv):
    """Parses the command-line arguments.

    Args:
        argv: the list of arguments, minus the name of the binary

    Returns:
        A dictionary-like object containing the results of the parse.
    """
    parser = argparse.ArgumentParser(
        description='Repeatedly upload the synchronization data in Cloud '
                    'Datastore up to the specified spreadsheet.')
    parser.add_argument(
        '--expected_upload_interval',
        metavar='SECONDS',
        type=float,
        default=300,
        help='The number of seconds to wait between uploads (on average).  We '
             'add jitter to this number to prevent the buildup of patterns, '
             'but this specifies the average of the wait times.')
    parser.add_argument(
        '--spreadsheet',
        metavar='SPREADSHEET_ID',
        type=str,
        required=True,
        help='The ID of the spreadsheet to update')
    parser.add_argument(
        '--datastore_namespace',
        metavar='NAMESPACE',
        type=str,
        default='scraper',
        help='The cloud datastore namespace to use in the current project.')
    parser.add_argument(
        '--prometheus_port',
        metavar='PORT',
        type=int,
        default=9090,
        help='The port on which metrics are exported.')
    parser.add_argument(
        '--webserver_port',
        metavar='PORT',
        type=int,
        default=80,
        help='The port on which a summary of the sheet is exported.')
    return parser.parse_args(argv)


KEYS = ['dropboxrsyncaddress', 'contact', 'lastsuccessfulcollection',
        'errorsincelastsuccessful', 'lastcollectionattempt',
        'maxrawfilemtimearchived']


def status_to_dict(status_entity):
    """Converts an Entity into a dictionary."""
    answer = {}
    answer[KEYS[0]] = status_entity.key.name
    for k in KEYS[1:]:
        answer[k] = status_entity.get(k, '')
    return answer


# A datatype to hold cached data for timed_locking_cache
CachedData = collections.namedtuple('CachedData', ['expiration', 'value'])


def timed_locking_cache(**kwargs):
    """A decorator that caches a functions results for a set period of time.

    Should be part of the stdlib, and actually is part of it in Python 3+.  Adds
    a 'nocache' argument to the kwargs of the constructed function, so be
    careful that this does not override an existing argument.

    The cache ignores keyword arguments.  TODO(make the cache smarter)
    """
    timeout = datetime.timedelta(**kwargs)

    def cacher(func):
        """The actual function that is applied to decorate the function."""
        cache = {}
        lock = threading.RLock()

        def cached_func(*args, **kwargs):
            """A cached version of the passed-in function."""
            lock.acquire()
            current = datetime.datetime.now()
            if 'nocache' in kwargs or \
                    args not in cache or \
                    cache[args].expiration < current:
                cache[args] = CachedData(expiration=current + timeout,
                                         value=func(*args))
            value = cache[args].value
            lock.release()
            return value

        # Add a clear_cache method to the returned function object to aid in
        # testing.  Code not in a *_test.py file should not use this method.
        cached_func.clear_cache = cache.clear
        return cached_func
    return cacher


@timed_locking_cache(seconds=30)
@DATASTORE_TIMES.time()
def get_fleet_data(namespace):
    """Returns a list of dictionaries, one for every entry requested.

    Each status has a dropboxrsyncaddress that contains rsync_url_fragment as a
    substring.
    """
    datastore_client = datastore.Client(namespace=namespace)
    query = datastore_client.query(kind='dropboxrsyncaddress')
    statuses = query.fetch()
    return [status_to_dict(status) for status in statuses]


class WebHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    """Print the ground truth from cloud datastore."""
    namespace = 'test'

    def do_GET(self):
        """Print out the ground truth from cloud datastore as a webpage."""
        parsed_path = urlparse.urlparse(self.path)
        logging.info('Request of %s from %s', parsed_path.path,
                     self.client_address)
        if parsed_path.path == '/':
            self.do_root_url()
        elif parsed_path.path == '/json_status':
            self.do_scraper_status(parsed_path.query)
        else:
            with REQUEST_TIMES_ERROR.time():
                self.send_error(404)

    @REQUEST_TIMES_ROOT_URL.time()
    def do_root_url(self):
        """Draw a table when a request comes in for '/'."""
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        print >> self.wfile, textwrap.dedent('''\
        <html>
        <head>
          <title>MLab Scraper Status</title>
          <style>
            table {
              border-collapse: collapse;
              margin-left: auto;
              margin-right: auto;
            }
            tr:nth-child(even) {
              background-color: #FFF;
            }
            tr:nth-child(even) {
              background-color: #EEE;
            }
          </style>
        </head>
        <body>
          <table><tr>''')
        try:
            data = get_fleet_data(WebHandler.namespace)
        # This will be used for debugging errors, so catching an overly-broad
        # exception is appropriate.
        # pylint: disable=broad-except
        except Exception as exc:
            logging.error('Unable to retrieve data from datastore: %s',
                          str(exc))
            print >> self.wfile, '</table>'
            print >> self.wfile, '<p>Datastore error:</p><pre>'
            traceback.print_exc(file=self.wfile)
            print >> self.wfile, '</pre></body></html>'
            return
        # pylint: enable=broad-except

        if not data:
            print >> self.wfile, '</table><p>NO DATA</p>'
            print >> self.wfile, '</body></html>'
            return
        else:
            for key in KEYS:
                print >> self.wfile, '     <th>%s</th>' % key
            print >> self.wfile, '  </tr>'
            rows = sorted([d.get(key, '') for key in KEYS] for d in data)
            for data in rows:
                print >> self.wfile, '  <tr>'
                for item in data:
                    print >> self.wfile, '     <td>%s</td>' % item
                print >> self.wfile, '    </tr>'
            print >> self.wfile, '    </table>'
        print >> self.wfile, '  <center><small>', time.ctime()
        print >> self.wfile, '    </small></center>'
        print >> self.wfile, '</body></html>'

    @REQUEST_TIMES_JSON.time()
    def do_scraper_status(self, query_string):
        """Give the status, in JSON form, of the specified rsync endpoints.

        This returns a JSON list of JSON objects, because it will return the
        status of all endpoints that contain a substring of the rsync_filter
        argument value.  If no such argument exists, or it is the empty string,
        or anything else goes wrong with the parsing, then this will return the
        status of every endpoint with status in cloud datastore.

        Args:
          query_string: the URL query string, not yet parsed.
        """
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        data = urlparse.parse_qs(query_string)
        rsync_url_fragment = data.get('rsync_filter', [])
        if rsync_url_fragment:
            rsync_url_fragment = rsync_url_fragment[0]
        else:
            rsync_url_fragment = ''
        endpoints = [entry for entry in get_fleet_data(WebHandler.namespace)
                     if rsync_url_fragment in entry['dropboxrsyncaddress']]
        # The JSON should always encode a non-empty object (not string or array)
        # for reasons described here:
        #   https://www.owasp.org/index.php/AJAX_Security_Cheat_Sheet
        output = {'result': endpoints}
        print >> self.wfile, json.dumps(output)


def start_webserver_in_new_thread(port):  # pragma: no cover
    """Starts the wbeserver to serve the ground truth page.

    Code cribbed from prometheus_client.
    """
    server_address = ('', port)

    class ThreadingSimpleServer(SocketServer.ThreadingMixIn,
                                BaseHTTPServer.HTTPServer):
        """Use the threading mix-in to avoid forking or blocking."""

    httpd = ThreadingSimpleServer(server_address, WebHandler)
    thread.start_new_thread(httpd.serve_forever, ())


class Spreadsheet(object):
    """Updates a given spreadsheet to mirror cloud datastore."""

    def __init__(self, service, sheet_id,
                 worksheet='Drop box status (auto updated)'):
        self._service = service
        self._sheet_id = sheet_id
        self._worksheet = worksheet

    def _retrieve_sheet_data(self):
        """Get the current data from the sheet.

        Used to ensure that the update process does not re-order rows.

        Raises:
           SyncException: The update failed.
        """
        # Sheet ranges have the form: <worksheet name>!<col1>:<col2>
        sheet_range = self._worksheet + '!A:' + chr(ord('A') + len(KEYS))
        result = self._service.spreadsheets().values().get(
            spreadsheetId=self._sheet_id, range=sheet_range).execute()
        if 'values' not in result:
            logging.error('Spreadsheet retrieve failed (%s)', result)
            raise SyncException(
                'Could not retrieve sheet data (%s)' % str(result))
        rows = result.get('values')
        if rows:
            return rows[0], rows[1:]
        else:
            logging.warning('No data found on spreadsheet.')
            return KEYS, []

    def _update_spreadsheet(self, header, rows):
        """Sets the contents of the spreadsheet.

        Used to set the contents of the spreadsheet, overriding all existing
        items in the sheet.

        Raises:
           SyncException: The update failed.
        """
        # Sheet ranges have the form: <worksheet name>!<col1><row1>:<col2><row2>
        # Column names are alphabetical starting with 'A'.  The code below will
        # break if the names go past 'Z'.
        # Row numbers are 1-indexed instead of zero-indexed and the first row
        # is reserved for the header.
        assert len(header) < 26
        update_range = (self._worksheet +
                        '!A1:' + chr(ord('A') + len(header))
                        + str(len(rows) + 1))
        body = {'values': [header] + rows}
        logging.info('About to update %s', update_range)
        response = self._service.spreadsheets().values().update(
            spreadsheetId=self._sheet_id, range=update_range,
            body=body, valueInputOption='RAW').execute()
        if not response['updatedRows']:
            logging.error('Spreadsheet update failed (%s)', response)
            raise SyncException(
                'Spreadsheet update failed (%s)' % str(response))

    def update(self, data):
        """Updates the contents of the spreadsheet.

        This respects the existing order of the rsync modules, but appends new
        rows for any rsync modules that did not previously exist in the sheet.

        Args:
          data: a list of dictionaries

        Raises:
           SyncException: The update failed.
        """
        updated_data = {d[KEYS[0]]: d for d in data}
        new_rows = []
        header, old_rows = self._retrieve_sheet_data()
        rsync_index = header.index(KEYS[0])
        for old_row in old_rows:
            rsync_url = old_row[rsync_index]
            if rsync_url in updated_data:
                new_row = [updated_data[rsync_url][h] for h in header]
                new_rows.append(new_row)
                del updated_data[rsync_url]
            else:
                new_rows.append(old_row)
        for rsync_url in sorted(updated_data):
            new_row = [updated_data[rsync_url][h] for h in header]
            new_rows.append(new_row)
        return self._update_spreadsheet(header, new_rows)


def parse_xdatetime(xdatetime):
    """Turn a datetime string into seconds since epoch.

    Data is stored in the coordinating spreadsheet as a date (plus optional
    time) string with a leading 'x' character.  The leading x is to prevent the
    spreadsheet from "helpfully" interpreting it as a datetime rather than just
    holding the string.  This converts from that string format into seconds
    since epoch.
    """
    if not xdatetime or xdatetime[0] != 'x':
        return None
    try:
        parsed_datetime = dateutil.parser.parse(xdatetime[1:])
        epoch = datetime.datetime(1970, 1, 1)
        return int((parsed_datetime - epoch).total_seconds())
    except ValueError:
        return None


def deconstruct_rsync_url(rsync_url):
    """Turns an rsync url into experiment, machine, and rsync_module parts.

    Returns None if the rsync_url does not conform to the required spec.
    """
    parts = re.compile(
        r'rsync://(.*)\.(mlab\d.[a-z]{3}\d[\dt]\.measurement-lab.org):\d*/(.*)')
    match = parts.match(rsync_url)
    if match is None:
        return None
    else:
        return match.group(1), match.group(2), match.group(3)


@timed_locking_cache(hours=1)
def get_kubernetes_json():  # pragma: no cover
    """Get the status of the system, in JSON, from the kubernetes server."""
    context = ssl.create_default_context()
    context.load_verify_locations(
        '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt')
    token = file('/var/run/secrets/kubernetes.io/serviceaccount/token',
                 'r').read()
    k8s_server = 'kubernetes.default.svc'
    conn = httplib.HTTPSConnection(k8s_server, context=context)
    conn.request('GET',
                 'https://' + k8s_server +
                 '/apis/extensions/v1beta1/deployments',
                 headers={'Authorization': 'Bearer ' + token})
    response = conn.getresponse()
    return json.load(response)


def get_deployed_rsync_urls(namespace):
    """Get a set of deployed rsync urls.

    We query the local Kubernetes master to get the config.
    """
    deployments_json = get_kubernetes_json()
    deployments = deployments_json['items']
    urls = []
    for deployment in deployments:
        metadata = deployment['metadata']
        if metadata['namespace'] != namespace:
            continue
        labels = deployment['spec']['selector']['matchLabels']
        rsync_url = ('rsync://{experiment}.{machine}:7999/'
                     '{rsync_module}'.format(**labels))
        urls.append(rsync_url)
    return set(urls)


class PrometheusDatastoreCollector(object):
    """A collector to forward the contents of cloud datastore to prometheus."""

    def __init__(self, namespace):
        self.namespace = namespace

    @REQUEST_TIMES_COLLECT.time()
    def collect(self):
        """Get the data from cloud datastore and yield a series of metrics."""

        last_success = prometheus_client.core.GaugeMetricFamily(
            'scraper_lastsuccessfulcollection',
            'Time of the last successful collection',
            labels=['experiment', 'machine', 'rsync_module'])
        last_attempt = prometheus_client.core.GaugeMetricFamily(
            'scraper_lastcollectionattempt',
            'Time of the last collection attempt',
            labels=['experiment', 'machine', 'rsync_module'])
        max_filetime = prometheus_client.core.GaugeMetricFamily(
            'scraper_maxrawfiletimearchived',
            'Time before which files may be deleted',
            labels=['experiment', 'machine', 'rsync_module'])
        deployed_urls = get_deployed_rsync_urls(self.namespace)
        data = [x for x in get_fleet_data(self.namespace)
                if x['dropboxrsyncaddress'] in deployed_urls]
        for fact in data:
            rsync_url = fact['dropboxrsyncaddress']
            labels = deconstruct_rsync_url(rsync_url)
            if labels is None:
                logging.error('Bad rsync url: %s', rsync_url)
                continue
            if 'lastsuccessfulcollection' in fact:
                timestamp = parse_xdatetime(fact['lastsuccessfulcollection'])
                if timestamp is not None:
                    last_success.add_metric(labels, timestamp)
            if 'lastcollectionattempt' in fact:
                timestamp = parse_xdatetime(fact['lastcollectionattempt'])
                if timestamp is not None:
                    last_attempt.add_metric(labels, timestamp)
            if 'maxrawfilemtimearchived' in fact:
                try:
                    timestamp = int(fact['maxrawfilemtimearchived'])
                    max_filetime.add_metric(labels, timestamp)
                except ValueError:
                    pass
        yield last_success
        yield last_attempt
        yield max_filetime


def main(argv):  # pragma: no cover
    """Update the spreadsheet in a loop.

    Set up the logging, parse the command line, set up monitoring, set up the
    datastore client, set up the spreadsheet client, set up the webserver, and
    then repeatedly update the spreadsheet and sleep.
    """
    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG,
        format='[%(asctime)s %(levelname)s %(filename)s:%(lineno)d] '
               '%(message)s')
    # Parse the commandline
    args = parse_args(argv[1:])
    WebHandler.namespace = args.datastore_namespace
    # Set up spreadsheet client
    creds = gce.AppAssertionCredentials()
    discovery_url = ('https://sheets.googleapis.com/$discovery/rest?'
                     'version=v4')
    sheets_service = apiclient.discovery.build(
        'sheets', 'v4', discoveryServiceUrl=discovery_url,
        credentials=creds, cache_discovery=False)
    spreadsheet = Spreadsheet(sheets_service, args.spreadsheet)
    # Set up the prometheus sync job
    prometheus_client.core.REGISTRY.register(
        PrometheusDatastoreCollector(args.datastore_namespace))
    # Set up the monitoring
    prometheus_client.start_http_server(args.prometheus_port)
    start_webserver_in_new_thread(args.webserver_port)
    # Repeatedly copy information from the datastore to the spreadsheet
    while True:
        # This code may be subject to transient errors in cloud datastore or
        # the sheets service. Intermittent failures of those services should
        # not crash this client, so we catch all Exceptions and log them
        # instead of crashing.
        # pylint: disable=broad-except
        try:
            with RUNS.time():
                # Download
                data = get_fleet_data(args.datastore_namespace)
                # Upload
                spreadsheet.update(data)
            SUCCESS.labels(message='success').inc()
        except (SyncException, Exception) as error:
            logging.error('Sync failed: %s', error)
            SUCCESS.labels(message=str(type(error))).inc()
        # pylint: enable=broad-except
        # Sleep, but never for longer than an hour.
        sleep_time = min(
            random.expovariate(1.0 / args.expected_upload_interval), 3600)
        logging.info('Sleeping for %g seconds', sleep_time)
        with SLEEPS.time():
            time.sleep(sleep_time)


if __name__ == '__main__':  # pragma: no cover
    main(sys.argv)
