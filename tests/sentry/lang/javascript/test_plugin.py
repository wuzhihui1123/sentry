from __future__ import absolute_import

import responses
import os.path

from mock import patch

from sentry.models import Event
from sentry.testutils import TestCase

BASE64_SOURCEMAP = 'data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiZ2VuZXJhdGVkLmpzIiwic291cmNlcyI6WyIvdGVzdC5qcyJdLCJuYW1lcyI6W10sIm1hcHBpbmdzIjoiO0FBQUEiLCJzb3VyY2VzQ29udGVudCI6WyJjb25zb2xlLmxvZyhcImhlbGxvLCBXb3JsZCFcIikiXX0='


def load_fixture(name):
    with open(os.path.join(os.path.dirname(__file__), 'fixtures', name)) as fp:
        return fp.read()


class JavascriptIntegrationTest(TestCase):
    @patch('sentry.lang.javascript.processor.fetch_url')
    def test_source_expansion(self, mock_fetch_url):
        data = {
            'message': 'hello',
            'platform': 'javascript',
            'sentry.interfaces.Exception': {
                'values': [{
                    'type': 'Error',
                    'stacktrace': {
                        'frames': [
                            {
                                'abs_path': 'http://example.com/foo.js',
                                'filename': 'foo.js',
                                'lineno': 4,
                                'colno': 0,
                            },
                            {
                                'abs_path': 'http://example.com/foo.js',
                                'filename': 'foo.js',
                                'lineno': 1,
                                'colno': 0,
                            },
                        ],
                    },
                }],
            }
        }

        mock_fetch_url.return_value.body = '\n'.join('hello world')

        resp = self._postWithHeader(data)
        assert resp.status_code, 200

        mock_fetch_url.assert_called_once_with(
            'http://example.com/foo.js', project=self.project)

        event = Event.objects.get()
        exception = event.interfaces['sentry.interfaces.Exception']
        frame_list = exception.values[0].stacktrace.frames

        frame = frame_list[0]
        assert frame.pre_context == ['h', 'e', 'l']
        assert frame.context_line == 'l'
        assert frame.post_context == ['o', ' ', 'w', 'o', 'r']

        frame = frame_list[1]
        assert frame.pre_context is None
        assert frame.context_line == 'h'
        assert frame.post_context == ['e', 'l', 'l', 'o', ' ']

    @patch('sentry.lang.javascript.processor.fetch_url')
    @patch('sentry.lang.javascript.processor.discover_sourcemap')
    def test_inlined_sources(self, mock_discover_sourcemap, mock_fetch_url):
        data = {
            'message': 'hello',
            'platform': 'javascript',
            'sentry.interfaces.Exception': {
                'values': [{
                    'type': 'Error',
                    'stacktrace': {
                        'frames': [
                            {
                                'abs_path': 'http://example.com/test.min.js',
                                'filename': 'test.js',
                                'lineno': 1,
                                'colno': 0,
                            },
                        ],
                    },
                }],
            }
        }

        mock_discover_sourcemap.return_value = BASE64_SOURCEMAP

        mock_fetch_url.return_value.url = 'http://example.com/test.min.js'
        mock_fetch_url.return_value.body = '\n'.join('<generated source>')

        resp = self._postWithHeader(data)
        assert resp.status_code, 200

        mock_fetch_url.assert_called_once_with(
            'http://example.com/test.min.js', project=self.project)

        event = Event.objects.get()
        exception = event.interfaces['sentry.interfaces.Exception']
        frame_list = exception.values[0].stacktrace.frames

        frame = frame_list[0]
        assert not frame.pre_context
        assert frame.context_line == 'console.log("hello, World!")'
        assert not frame.post_context

    @responses.activate
    def test_sourcemap_source_expansion(self):
        responses.add(responses.GET, 'http://example.com/file.min.js',
                      body=load_fixture('file.min.js'))
        responses.add(responses.GET, 'http://example.com/file1.js',
                      body=load_fixture('file1.js'))
        responses.add(responses.GET, 'http://example.com/file2.js',
                      body=load_fixture('file2.js'))
        responses.add(responses.GET, 'http://example.com/file.sourcemap.js',
                      body=load_fixture('file.sourcemap.js'))

        data = {
            'message': 'hello',
            'platform': 'javascript',
            'sentry.interfaces.Exception': {
                'values': [{
                    'type': 'Error',
                    'stacktrace': {
                        'frames': [
                            {
                                'abs_path': 'http://example.com/file.min.js',
                                'filename': 'file.min.js',
                                'lineno': 1,
                                'colno': 39,
                            },
                        ],
                    },
                }],
            }
        }

        resp = self._postWithHeader(data)
        assert resp.status_code, 200

        event = Event.objects.get()
        exception = event.interfaces['sentry.interfaces.Exception']
        frame_list = exception.values[0].stacktrace.frames

        frame = frame_list[0]
        assert not frame.errors
        assert frame.pre_context == [
            'function add(a, b) {',
            '\t"use strict";',
        ]
        assert frame.context_line == '\treturn a + b;'
        assert frame.post_context == ['}']
