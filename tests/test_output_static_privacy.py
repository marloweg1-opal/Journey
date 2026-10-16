import unittest
import io
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import mini_ark_server as bridge


class OutputStaticPrivacyTests(unittest.TestCase):
    def make_handler(self, directory, method, path='/'):
        handler = object.__new__(bridge.Handler)
        handler.directory = str(directory)
        handler.path = path
        handler.command = method
        handler.request_version = 'HTTP/1.1'
        handler.requestline = f'{method} {path} HTTP/1.1'
        handler.headers = {}
        handler.wfile = io.BytesIO()
        handler.log_message = Mock()
        return handler

    def test_directory_listing_denied_without_enumeration(self):
        handler = self.make_handler('unused', 'GET')
        with patch('os.listdir', side_effect=AssertionError('must not enumerate')):
            self.assertIsNone(handler.list_directory('unused'))
        response = handler.wfile.getvalue()
        self.assertIn(b'403', response.split(b'\r\n')[0])
        self.assertIn(b'Cache-Control: no-store', response)
        self.assertEqual(response.split(b'\r\n\r\n', 1)[1], b'')

    def test_get_and_head_cannot_list_synthetic_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'sensitive-fixture-name.txt').write_text('synthetic')
            for method in ('GET', 'HEAD'):
                with self.subTest(method=method):
                    handler = self.make_handler(directory, method)
                    getattr(handler, 'do_' + method)()
                    response = handler.wfile.getvalue()
                    self.assertIn(b'403', response.split(b'\r\n')[0])
                    self.assertNotIn(b'sensitive-fixture-name', response)
                    self.assertEqual(response.split(b'\r\n\r\n', 1)[1], b'')

    def test_explicit_index_remains_available_without_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'index.html').write_text('synthetic-index')
            for method in ('GET', 'HEAD'):
                with self.subTest(method=method):
                    handler = self.make_handler(directory, method)
                    handler.list_directory = Mock(side_effect=AssertionError('no listing'))
                    getattr(handler, 'do_' + method)()
                    response = handler.wfile.getvalue()
                    self.assertIn(b'200', response.split(b'\r\n')[0])
                    body = response.split(b'\r\n\r\n', 1)[1]
                    self.assertEqual(body, b'synthetic-index' if method == 'GET' else b'')

    def test_generated_and_configuration_outputs_denied_on_get_and_head(self):
        paths = ('/docs/status.md', '/logs/run.json', '/handoffs_inbox/review.json',
                 '/config/policy.json', '/config.json', '/inventory_report.md',
                 '/ark.sqlite-journal', '/state.db-wal', '/asset_pipeline/asset-index.json',
                 '/%64ocs/status.txt', '/LOGS/a.txt', '/x%5clogs%5ca.txt',
                 '/config.json.', '/config.json%20', '/private./file.txt',
                 '/docs%20/file.txt', '/state.db::$DATA', '/config.json%3A%3A$DATA',
                 '/file.txt%00.png', '/x%5cprivate.%5cfile.txt')
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(bridge._private_request_path(path))
                handler = object.__new__(bridge.Handler)
                handler.path = path
                handler.send_response = Mock()
                handler.send_header = Mock()
                handler.end_headers = Mock()
                with patch.object(bridge.SimpleHTTPRequestHandler, 'do_HEAD') as head:
                    handler.do_HEAD()
                    head.assert_not_called()
                    handler.send_response.assert_called_once_with(403)
                with patch.object(bridge, '_json_response') as response, \
                     patch.object(bridge.SimpleHTTPRequestHandler, 'do_GET') as get:
                    handler._get()
                    get.assert_not_called()
                    self.assertEqual(response.call_args.args[2], 403)

    def test_existing_ui_and_api_paths_not_reclassified(self):
        for path in ('/', '/index.html', '/api/status', '/api/logs', '/asset_pipeline/library/frame.png'):
            self.assertFalse(bridge._private_request_path(path))

    def test_windows_aliases_denied_by_real_get_and_head_dispatch(self):
        for path in ('/config.json.', '/private%20/a.txt', '/state.db%3A%3A$DATA'):
            for method in ('GET', 'HEAD'):
                with self.subTest(path=path, method=method):
                    handler = self.make_handler('unused', method, path)
                    with patch.object(bridge.SimpleHTTPRequestHandler, 'send_head',
                                      side_effect=AssertionError('must not access disk')):
                        getattr(handler, 'do_' + method)()
                    response = handler.wfile.getvalue()
                    self.assertIn(b'403', response.split(b'\r\n')[0])

    def test_url_query_does_not_reclassify_valid_resource(self):
        for path in ('/index.html?at=12:00', '/api/logs?at=12:00',
                     '/asset_pipeline/library/frame.png?label=hello%20'):
            self.assertFalse(bridge._private_request_path(path))

    def test_unlisted_static_files_denied_without_disk_access(self):
        for path in ('/ark.py', '/report.json', '/asset_pipeline/outbox/job/image.png',
                     '/asset_pipeline/library/unreviewed.png', '/index.html/extra',
                     '/x/../index.html', '/INDEX.HTML'):
            for method in ('GET', 'HEAD'):
                with self.subTest(path=path, method=method):
                    handler = self.make_handler('unused', method, path)
                    with patch.object(Path, 'lstat', side_effect=AssertionError('no probing')):
                        getattr(handler, 'do_' + method)()
                    self.assertIn(b'403', handler.wfile.getvalue().split(b'\r\n')[0])

    def test_public_frames_are_exact_resources_and_serve_on_get_and_head(self):
        with tempfile.TemporaryDirectory() as directory:
            for resource in bridge.PUBLIC_STATIC_PATHS - {'/index.html'}:
                target = Path(directory) / resource.lstrip('/')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'synthetic-frame')
                for method in ('GET', 'HEAD'):
                    handler = self.make_handler(directory, method, resource + '?v=1')
                    getattr(handler, 'do_' + method)()
                    response = handler.wfile.getvalue()
                    self.assertIn(b'200', response.split(b'\r\n')[0])
                    self.assertEqual(response.split(b'\r\n\r\n', 1)[1],
                                     b'synthetic-frame' if method == 'GET' else b'')

    def test_reparse_ancestor_denied_before_child_or_file_open(self):
        with tempfile.TemporaryDirectory() as directory:
            handler = self.make_handler(directory, 'HEAD', '/index.html')
            original = Path.lstat
            def fake_lstat(path, *args, **kwargs):
                if path == Path(directory):
                    return Mock(st_mode=0, st_file_attributes=0x400)
                if path == Path(directory) / 'index.html':
                    self.fail('must not touch child of reparse directory')
                return original(path, *args, **kwargs)
            with patch.object(Path, 'lstat', fake_lstat), \
                 patch.object(bridge.SimpleHTTPRequestHandler, 'send_head',
                              side_effect=AssertionError('must not open file')):
                handler.do_HEAD()
            self.assertIn(b'403', handler.wfile.getvalue().split(b'\r\n')[0])

    def test_navigator_css_resources_match_public_contract(self):
        import re
        html = (bridge.ROOT / 'index.html').read_text(encoding='utf-8')
        resources = re.findall(r'url\("([^"\n]+)"\)', html)
        self.assertEqual({'/' + value for value in resources},
                         bridge.PUBLIC_STATIC_PATHS - {'/index.html'})
