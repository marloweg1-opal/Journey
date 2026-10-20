import unittest
from unittest.mock import Mock, patch

import mini_ark_server as bridge


class BridgeHeadPrivacyTests(unittest.TestCase):
    def test_private_head_denies_before_static_handler_without_body(self):
        for path in ('/private/secret.json', '/.git/config', '/ark.sqlite',
                     '/ark.sqlite-wal', '/ark.sqlite-shm', '/%70rivate/data',
                     '/PUBLIC/../PRIVATE/data', '/private%5cdata', '/ark.sqlite?x=1'):
            with self.subTest(path=path), \
                    patch.object(bridge.SimpleHTTPRequestHandler, 'do_HEAD') as base:
                handler = object.__new__(bridge.Handler)
                handler.path = path
                handler.send_response = Mock()
                handler.send_header = Mock()
                handler.end_headers = Mock()
                handler.wfile = Mock()
                handler.do_HEAD()
                handler.send_response.assert_called_once_with(403)
                handler.send_header.assert_any_call('Content-Length', '0')
                handler.wfile.write.assert_not_called()
                base.assert_not_called()

    def test_public_head_keeps_static_behavior(self):
        with patch.object(bridge.SimpleHTTPRequestHandler, 'do_HEAD') as base:
            handler = object.__new__(bridge.Handler)
            handler.path = '/index.html'
            handler.do_HEAD()
            base.assert_called_once()

    def test_get_uses_same_private_filter(self):
        handler = object.__new__(bridge.Handler)
        handler.path = '/private/fixture.json'
        with patch.object(bridge, '_json_response') as response, \
                patch.object(bridge.SimpleHTTPRequestHandler, 'do_GET') as base:
            handler._get()
        self.assertEqual(response.call_args.args[2], 403)
        base.assert_not_called()
