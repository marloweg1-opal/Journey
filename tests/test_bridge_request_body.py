import io
import unittest
from email.message import Message
from unittest.mock import Mock, patch

import mini_ark_server as bridge


class BridgeRequestBodyTests(unittest.TestCase):
    def handler(self, body=b'{}', length=None):
        handler = object.__new__(bridge.Handler)
        handler.headers = Message()
        handler.headers['Content-Length'] = str(len(body)) if length is None else length
        handler.rfile = io.BytesIO(body)
        handler.path = '/api/actions/media-inventory-resume'
        return handler

    def test_valid_object_and_empty_body(self):
        self.assertEqual(bridge._read_json_body(self.handler(b'{"confirmed":true}')), {'confirmed': True})
        self.assertEqual(bridge._read_json_body(self.handler(b'')), {})

    def test_invalid_lengths_never_read(self):
        for value in ('-1', '+2', 'bad', '1, 2', '99999999999999999999'):
            with self.subTest(value=value):
                handler = self.handler(length=value)
                handler.rfile = Mock()
                with self.assertRaises(bridge.RequestBodyError):
                    bridge._read_json_body(handler)
                handler.rfile.read.assert_not_called()

    def test_oversize_never_reads(self):
        handler = self.handler(length=str(bridge.MAX_REQUEST_BODY_BYTES + 1))
        handler.rfile = Mock()
        with self.assertRaises(bridge.RequestBodyError) as error:
            bridge._read_json_body(handler)
        self.assertEqual(error.exception.status, 413)
        handler.rfile.read.assert_not_called()

    def test_boundary_body_length_is_accepted(self):
        with patch.object(bridge, 'MAX_REQUEST_BODY_BYTES', 2):
            self.assertEqual(bridge._read_json_body(self.handler()), {})

    def test_ambiguous_and_encoded_bodies_never_read(self):
        for header, value in (('Content-Length', '2'), ('Transfer-Encoding', 'chunked'),
                              ('Content-Encoding', 'gzip')):
            with self.subTest(header=header):
                handler = self.handler()
                handler.headers[header] = value
                handler.rfile = Mock()
                with self.assertRaises(bridge.RequestBodyError):
                    bridge._read_json_body(handler)
                handler.rfile.read.assert_not_called()

    def test_invalid_json_cannot_dispatch_an_action(self):
        for body in (b'{', b'null', b'[]', b'false', b'"text"', b'\xff', b'[' * 2000):
            with self.subTest(body_length=len(body)), \
                    patch.object(bridge, 'run_action') as action, \
                    patch.object(bridge, '_json_response') as response:
                handler = self.handler(body)
                handler.do_POST()
                action.assert_not_called()
                self.assertEqual(response.call_args.args[2], 400)
                self.assertTrue(handler.close_connection)

    def test_short_body_is_rejected(self):
        with self.assertRaisesRegex(bridge.RequestBodyError, 'Incomplete'):
            bridge._read_json_body(self.handler(b'{}', length='5'))

    def test_duplicate_fields_cannot_dispatch(self):
        bodies = (b'{"confirmed":false,"confirmed":true}',
                  b'{"scope":"first","scope":"second"}',
                  b'{"options":{"mode":"observe","mode":"execute"}}',
                  br'{"confirmed":false,"\u0063onfirmed":true}')
        for body in bodies:
            with self.subTest(body=body), \
                    patch.object(bridge, 'run_action') as action, \
                    patch.object(bridge, '_json_response') as response:
                self.handler(body).do_POST()
                action.assert_not_called()
                self.assertEqual(response.call_args.args[2], 400)

    def test_same_field_in_separate_objects_is_valid(self):
        body = b'{"items":[{"name":"one"},{"name":"two"}]}'
        self.assertEqual(bridge._read_json_body(self.handler(body)),
                         {'items': [{'name': 'one'}, {'name': 'two'}]})
