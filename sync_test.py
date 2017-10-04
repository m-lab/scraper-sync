#!/usr/bin/env python
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

# No docstrings required for tests.
# Tests need to be methods of classes to aid in organization of tests. Using
#   the 'self' variable is not required.
# "Too many public methods" here means "many tests", which is good not bad.
# This code is in a subdirectory, but is intended to stand alone, so it uses
#   what look like relative imports to the linter
# pylint: disable=missing-docstring, no-self-use, too-many-public-methods
# pylint: disable=relative-import

import datetime
import json
import StringIO
import unittest

import freezegun
import mock
import requests
import testfixtures

import sync

# pylint: disable=no-name-in-module
from google.cloud import datastore
import google.auth.credentials
# pylint: enable=no-name-in-module


class EmulatorCreds(google.auth.credentials.Credentials):
    """A mock credential object.

    Used to avoid the need for auth entirely when using local versions of cloud
    services.

    Based on:
       https://github.com/GoogleCloudPlatform/google-cloud-python/blob/3caed41b88eb58673ee5c3396afa3f8fff97d4d4/test_utils/test_utils/system.py#L33
    """

    def refresh(self, _request):  # pragma: no cover
        raise RuntimeError('Should never be called.')


DATASTORE_DATA = [
    ('rsync://utility.mlab.mlab4.prg01.measurement-lab.org:7999/switch',
     {'lastsuccessfulcollection': 'x2017-03-28',
      'errorsincelastsuccessful': '',
      'lastcollectionattempt': 'x2017-03-29-21:22',
      'maxrawfilemtimearchived': 1490746201L}),
    ('rsync://utility.mlab.mlab4.prg01.measurement-lab.org:7999/utilization',
     {'errorsincelastsuccessful': '',
      'lastsuccessfulcollection': 'x2017-03-28',
      'lastcollectionattempt': 'x2017-03-29-21:04',
      'maxrawfilemtimearchived': 1490746202L}),
    ('rsync://utility.mlab.mlab4.sea02.measurement-lab.org:7999/switch',
     {'lastcollectionattempt': 'x2017-03-29-15:46',
      'errorsincelastsuccessful':
      '[2017-03-29 15:49:07,364 ERROR run_scraper.py:196] '
      'Scrape and upload failed: 1'})]


def setUpModule():
    creds = EmulatorCreds()
    sync.WebHandler.namespace = 'test'
    datastore_client = datastore.Client(project='mlab-sandbox',
                                        namespace='test',
                                        credentials=creds,
                                        _http=requests.Session())
    with datastore_client.transaction():
        for url, data in DATASTORE_DATA:
            entity = datastore.Entity(
                key=datastore_client.key('dropboxrsyncaddress', url))
            for (key, value) in data.items():
                entity[key] = value
            datastore_client.put(entity)
    datastore_patcher = mock.patch.object(datastore, 'Client',
                                          return_value=datastore_client)
    datastore_patcher.start()


class TestSync(unittest.TestCase):

    class FakeEntity(dict):

        def __init__(self, key, kv_pairs):
            dict.__init__(self, **kv_pairs)
            self.key = mock.Mock()
            self.key.name = key

    def setUp(self):
        def read_json_from_disk():
            return json.load(open('testdata_deployments.json'))
        self.json_patcher = mock.patch.object(
            sync, 'get_kubernetes_json',
            side_effect=read_json_from_disk)
        self.json_patcher.start()

        self.test_datastore_data = [
            TestSync.FakeEntity(*data) for data in DATASTORE_DATA]

        self.mock_handler = mock.Mock(sync.WebHandler)
        self.mock_handler.wfile = StringIO.StringIO()
        self.mock_handler.client_address = (1234, '127.0.0.1')
        sync.get_fleet_data.clear_cache()

    def tearDown(self):
        self.json_patcher.stop()

    def test_parse_args_no_spreadsheet(self):
        with self.assertRaises(SystemExit):
            with testfixtures.OutputCapture() as _:
                sync.parse_args([])

    def test_parse_args_help(self):
        with self.assertRaises(SystemExit):
            with testfixtures.OutputCapture() as _:
                sync.parse_args(['-h'])

    def test_parse_args(self):
        args = sync.parse_args(['--spreadsheet', 'hello'])
        self.assertEqual(args.spreadsheet, 'hello')
        self.assertTrue(args.expected_upload_interval > 0)
        self.assertIs(type(args.datastore_namespace), str)
        self.assertIs(type(args.prometheus_port), int)
        self.assertIs(type(args.webserver_port), int)

    def test_get_fleet_data(self):
        returned_answers = sync.get_fleet_data('scraper')
        correct_answers = [
            {'dropboxrsyncaddress': 'rsync://utility.mlab.mlab4.prg01.'
                                    'measurement-lab.org:7999/switch',
             'contact': '',
             'lastsuccessfulcollection': 'x2017-03-28',
             'errorsincelastsuccessful': '',
             'lastcollectionattempt': 'x2017-03-29-21:22',
             'maxrawfilemtimearchived': 1490746201L},
            {'dropboxrsyncaddress': 'rsync://utility.mlab.mlab4.prg01.'
                                    'measurement-lab.org:7999/utilization',
             'contact': '',
             'errorsincelastsuccessful': '',
             'lastsuccessfulcollection': 'x2017-03-28',
             'lastcollectionattempt': 'x2017-03-29-21:04',
             'maxrawfilemtimearchived': 1490746202L},
            {'dropboxrsyncaddress': 'rsync://utility.mlab.mlab4.sea02'
                                    '.measurement-lab.org:7999/switch',
             'contact': '',
             'errorsincelastsuccessful':
                 '[2017-03-29 15:49:07,364 ERROR run_scraper.py:196] '
                 'Scrape and upload failed: 1',
             'lastsuccessfulcollection': '',
             'lastcollectionattempt': 'x2017-03-29-15:46',
             'maxrawfilemtimearchived': ''}]
        self.assertItemsEqual(returned_answers, correct_answers)

    def test_get_fleet_data_subsets(self):
        sea02_switch = {
            'dropboxrsyncaddress': 'rsync://utility.mlab.mlab4.sea02'
                                   '.measurement-lab.org:7999/switch',
            'contact': '',
            'errorsincelastsuccessful':
                '[2017-03-29 15:49:07,364 ERROR run_scraper.py:196] '
                'Scrape and upload failed: 1',
            'lastsuccessfulcollection': '',
            'lastcollectionattempt': 'x2017-03-29-15:46',
            'maxrawfilemtimearchived': ''}
        sea02_only = [x for x in sync.get_fleet_data('scraper')
                      if 'sea02' in x['dropboxrsyncaddress']]
        self.assertItemsEqual(sea02_only, [sea02_switch])

    def test_do_get(self):
        sync.WebHandler.do_root_url(self.mock_handler)
        self.assertEqual(self.mock_handler.wfile.getvalue().count('<tr>'), 4)

    @mock.patch.object(sync, 'datastore')
    def test_do_get_no_data(self, mock_datastore):
        mock_client = mock.Mock()
        mock_datastore.Client.return_value = mock_client
        mock_client.query().fetch.return_value = []

        sync.WebHandler.do_root_url(self.mock_handler)

        self.assertEqual(self.mock_handler.wfile.getvalue().count('<td>'), 0)

    @mock.patch.object(sync, 'datastore')
    @testfixtures.log_capture()
    def test_do_get_datastore_failure(self, mock_datastore, log):
        mock_datastore.Client.side_effect = Exception

        sync.WebHandler.do_root_url(self.mock_handler)

        self.assertEqual(self.mock_handler.wfile.getvalue().count('<td>'), 0)
        self.assertEqual(self.mock_handler.wfile.getvalue().count('<pre>'), 1)
        self.assertIn('ERROR', [x.levelname for x in log.records])

    def test_docstring_exists(self):
        self.assertIsNotNone(sync.__doc__)

    @testfixtures.log_capture()
    def test_spreadsheet_empty_sheet(self, log):
        mock_service = mock.Mock()
        mock_service.spreadsheets().values().get().execute.return_value = {
            'values': []
        }
        mock_service.spreadsheets().values().update().execute.return_value = {
            'updatedRows': 'a true value'
        }

        sheet = sync.Spreadsheet(mock_service, 'test_id')
        sheet.update(sync.get_fleet_data('test_namespace'))

        _args, kwargs = mock_service.spreadsheets().values().update.call_args
        new_values = kwargs['body']['values']
        mock_service.spreadsheets().values().get().execute.assert_called()
        mock_service.spreadsheets().values().update().execute.assert_called()
        self.assertEqual(new_values[0], sync.KEYS)
        # One header row, three rows from datastore
        self.assertEqual(len(new_values), 4)
        self.assertIn('WARNING', [x.levelname for x in log.records])

    def test_spreadsheet_partly_filled(self):
        mock_service = mock.Mock()
        mock_service.spreadsheets().values().get().execute.return_value = {
            'values': [sync.KEYS] +
                      [['rsync://utility.mlab.mlab4.prg01.'
                        'measurement-lab.org:7999/switch'] +
                       ['' for _ in range(len(sync.KEYS) - 1)],
                       ['rsync://test'] +
                       ['' for _ in range(len(sync.KEYS) - 1)]]
        }
        mock_service.spreadsheets().values().update().execute.return_value = {
            'updatedRows': 'a true value'
        }

        sheet = sync.Spreadsheet(mock_service, 'test_id')
        sheet.update(sync.get_fleet_data('test_namespace'))

        _args, kwargs = mock_service.spreadsheets().values().update.call_args
        new_values = kwargs['body']['values']
        mock_service.spreadsheets().values().get().execute.assert_called()
        mock_service.spreadsheets().values().update().execute.assert_called()
        self.assertEqual(new_values[0], sync.KEYS)
        # One header row, three rows from datastore, one for rsync://test
        self.assertEqual(len(new_values), 5)

    @testfixtures.log_capture()
    def test_spreadsheet_update_fails(self, log):
        mock_service = mock.Mock()
        mock_service.spreadsheets().values().get().execute.return_value = {
            'values': [sync.KEYS] +
                      [['rsync://test'] +
                       ['' for _ in range(len(sync.KEYS) - 1)]]
        }
        mock_service.spreadsheets().values().update().execute.return_value = {
            'updatedRows': False
        }
        sheet = sync.Spreadsheet(mock_service, 'test_id')
        with self.assertRaises(sync.SyncException):
            sheet.update(sync.get_fleet_data('test_namespace'))

        mock_service.spreadsheets().values().get().execute.assert_called()
        mock_service.spreadsheets().values().update().execute.assert_called()
        self.assertIn('ERROR', [x.levelname for x in log.records])

    @testfixtures.log_capture()
    def test_spreadsheet_retrieve_fails(self, log):
        mock_service = mock.Mock()
        mock_service.spreadsheets().values().get().execute.return_value = {}

        sheet = sync.Spreadsheet(mock_service, 'test_id')
        with self.assertRaises(sync.SyncException):
            sheet.update(sync.get_fleet_data('test_namespace'))

        mock_service.spreadsheets().values().get().execute.assert_called()
        self.assertIn('ERROR', [x.levelname for x in log.records])

    def test_parse_xdatetime(self):
        self.assertEqual(sync.parse_xdatetime('x1970-1-1'), 0)
        self.assertEqual(sync.parse_xdatetime('x1970-1-1 00:01:00'), 60)
        self.assertEqual(sync.parse_xdatetime(''), None)
        self.assertEqual(sync.parse_xdatetime('1970-1-1'), None)
        self.assertEqual(sync.parse_xdatetime('x1970-1-1 BADDATA'), None)

    def test_prometheus_forwarding(self):
        collector = sync.PrometheusDatastoreCollector('scraper')
        metrics = list(collector.collect())
        self.assertEqual(set(x.name for x in metrics),
                         set(['scraper_lastsuccessfulcollection',
                              'scraper_lastcollectionattempt',
                              'scraper_maxrawfiletimearchived']))
        for metric in metrics:
            # spot-check one of the metrics
            if metric.name == 'scraper_maxrawfiletimearchived':
                self.assertEqual(set(x[2] for x in metric.samples),
                                 set([1490746201L, 1490746202L]))
                self.assertIn(
                    tuple({'machine': 'mlab4.prg01.measurement-lab.org',
                           'rsync_module': 'switch',
                           'experiment': 'utility.mlab'}.items()),
                    set(tuple(x[1].items()) for x in metric.samples))

    @mock.patch.object(sync, 'datastore')
    @testfixtures.log_capture()
    def test_prometheus_forwarding_with_bad_data(self, mock_datastore, log):
        # Put a bad value in the datastore.
        mock_client = mock.Mock()
        mock_datastore.Client.return_value = mock_client
        self.test_datastore_data.append(
            TestSync.FakeEntity('rsync://badbad', {}))
        mock_client.query().fetch.return_value = self.test_datastore_data

        # Add a bad value to all of the good values returned by
        # get_deployed_rsync_urls().
        rsync_urls_with_bad_value_added = set([
            'rsync://badbad',
        ]).union(sync.get_deployed_rsync_urls('scraper'))

        # Make get_deployed_rsync_urls() return the set with the bad
        # value.
        patcher = mock.patch('sync.get_deployed_rsync_urls')
        mock_rsync_urls = patcher.start()
        mock_rsync_urls.return_value = rsync_urls_with_bad_value_added

        # Verify that having a bad value in the system doesn't crash the
        # collector.
        collector = sync.PrometheusDatastoreCollector('scraper')
        metrics = list(collector.collect())
        self.assertEqual(set(x.name for x in metrics),
                         set(['scraper_lastsuccessfulcollection',
                              'scraper_lastcollectionattempt',
                              'scraper_maxrawfiletimearchived']))
        for metric in metrics:
            # spot-check one of the metrics
            if metric.name == 'scraper_maxrawfiletimearchived':
                self.assertEqual(set(x[2] for x in metric.samples),
                                 set([1490746201L, 1490746202L]))
        self.assertIn('ERROR', [x.levelname for x in log.records])

    @mock.patch.object(sync, 'datastore')
    @testfixtures.log_capture()
    def test_prometheus_forwarding_and_retired_sites(self, mock_datastore):
        # Add a datastore entry for a site that should no longer be published.
        # Then confirm that it is filtered from exported metrics.
        mock_client = mock.Mock()
        mock_datastore.Client.return_value = mock_client
        self.test_datastore_data.append(
            TestSync.FakeEntity(
                'rsync://ndt.iupui.mlab4.lhr01.measurement-lab.org:7999/ndt',
                {'lastsuccessfulcollection': 'x2017-03-28',
                 'errorsincelastsuccessful': '',
                 'lastcollectionattempt': 'x2017-03-29-21:22',
                 'maxrawfilemtimearchived': 1490746201L}))
        mock_client.query().fetch.return_value = self.test_datastore_data

        collector = sync.PrometheusDatastoreCollector('scraper')
        metrics = list(collector.collect())
        self.assertEqual(set(x.name for x in metrics),
                         set(['scraper_lastsuccessfulcollection',
                              'scraper_lastcollectionattempt',
                              'scraper_maxrawfiletimearchived']))
        for metric in metrics:
            for sample in metric.samples:
                self.assertNotEqual(sample[1]['machine'],
                                    'lhr01.measurement-lab.org')

    def test_deconstruct_rsync_url(self):
        self.assertEqual(
            sync.deconstruct_rsync_url(
                'rsync://utility.mlab.mlab4.prg01.measurement-lab.org:7999'
                '/utilization'),
            ('utility.mlab', 'mlab4.prg01.measurement-lab.org', 'utilization'))
        self.assertEqual(
            sync.deconstruct_rsync_url(
                'rsync://utility.mlab.BAD.prg01.measurement-lab.org:7999'
                '/utilization'),
            None)
        self.assertEqual(
            sync.deconstruct_rsync_url(
                'rsync://utility.mlab.mlab4.nuq0t.measurement-lab.org:7999'
                '/utilization'),
            ('utility.mlab', 'mlab4.nuq0t.measurement-lab.org', 'utilization'))

    def test_get_deployed_rsync_urls(self):
        self.assertIn('rsync://utility.mlab.mlab4.atl06.measurement-lab.org'
                      ':7999/utilization',
                      sync.get_deployed_rsync_urls('scraper'))
        self.assertNotIn('rsync://utility.mlab.mlab3.atl06.measurement-lab.org'
                         ':7999/utilization',
                         sync.get_deployed_rsync_urls('scraper'))
        self.assertIn('rsync://utility.mlab.mlab4.atl05.measurement-lab.org'
                      ':7999/utilization',
                      sync.get_deployed_rsync_urls('scraper'))

    def test_timed_cache(self):
        args = []

        @sync.timed_cache(hours=1)
        def max_once_per_arg_per_hour(arg):
            args.append(arg)
            return len(args)

        with freezegun.freeze_time('2016-10-26 18:10:00 UTC') as frozen_time:
            self.assertEqual(max_once_per_arg_per_hour('hello'), 1)
            self.assertEqual(['hello'], args)
            self.assertEqual(max_once_per_arg_per_hour('hello'), 1)
            self.assertEqual(['hello'], args)
            self.assertEqual(max_once_per_arg_per_hour('bye'), 2)
            self.assertEqual(['hello', 'bye'], args)

            frozen_time.tick(datetime.timedelta(hours=2))

            self.assertEqual(max_once_per_arg_per_hour('hello'), 3)
            self.assertEqual(['hello', 'bye', 'hello'], args)
            self.assertEqual(max_once_per_arg_per_hour('hello'), 3)
            self.assertEqual(['hello', 'bye', 'hello'], args)

    def test_timed_cache_nocache_kwarg(self):
        args = []

        @sync.timed_cache(hours=1)
        def max_once_per_arg_per_hour(arg):
            args.append(arg)
            return len(args)

        with freezegun.freeze_time('2016-10-26 18:10:00 UTC'):
            # Put 'hello' in the cache.
            self.assertEqual(max_once_per_arg_per_hour('hello'), 1)
            self.assertEqual(['hello'], args)
            # The nocache keyword argument should cause the cache to be ignored
            # pylint: disable=unexpected-keyword-arg
            self.assertEqual(max_once_per_arg_per_hour('hello', nocache=True),
                             2)
            # pylint: enable=unexpected-keyword-arg
            self.assertEqual(['hello', 'hello'], args)
            # ...but that should not effect the caching of future calls.
            self.assertEqual(max_once_per_arg_per_hour('hello'), 2)
            self.assertEqual(['hello', 'hello'], args)

    def test_deployed_rsync_urls(self):
        urls = sync.get_deployed_rsync_urls('scraper')
        self.assertTrue(len(urls) > 5)

    def test_do_get_root(self):
        self.mock_handler.path = '/'
        self.assertEqual(self.mock_handler.do_root_url.call_count, 0)
        sync.WebHandler.do_GET(self.mock_handler)
        self.assertEqual(self.mock_handler.do_root_url.call_count, 1)

    def test_do_get_json_status(self):
        self.mock_handler.path = '/json_status?rsync_filter=thing'
        self.assertEqual(self.mock_handler.do_scraper_status.call_count, 0)
        sync.WebHandler.do_GET(self.mock_handler)
        self.assertEqual(self.mock_handler.do_scraper_status.call_count, 1)
        self.assertEqual(self.mock_handler.do_scraper_status.call_args[0],
                         ('rsync_filter=thing',))

    def test_do_404_on_bad_urls(self):
        self.mock_handler.path = 'BAD'
        self.assertEqual(self.mock_handler.send_error.call_count, 0)
        sync.WebHandler.do_GET(self.mock_handler)
        self.assertEqual(self.mock_handler.send_error.call_count, 1)

    def test_do_scraper_status_bad_args(self):
        sync.WebHandler.do_scraper_status(self.mock_handler, 'f=g')
        result = json.loads(self.mock_handler.wfile.getvalue())['result']
        self.assertEqual(len(result), 3)

    def test_do_scraper_status_sea02(self):
        self.mock_handler.namespace = 'test'
        sync.WebHandler.do_scraper_status(self.mock_handler,
                                          'rsync_filter=sea02')
        result = json.loads(self.mock_handler.wfile.getvalue())['result']
        self.assertEqual(len(result), 1)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
