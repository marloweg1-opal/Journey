"""Real loopback lifecycle and lock ownership checks."""

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import json
import os
import subprocess
import sys
import unittest
from urllib.request import Request,urlopen
from unittest.mock import patch

from journey_navigator.__main__ import Navigator
from journey_navigator.session import SessionOwner,build_info,protect
from journey_navigator.workbench import Workbench


ROOT=Path(__file__).resolve().parents[1]


class NavigatorSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary=TemporaryDirectory(prefix='journey-lifecycle-')
        self.addCleanup(self.temporary.cleanup)
        self.data=Path(self.temporary.name).resolve()/'Checkpoint'
        self.data.mkdir()

    def test_same_build_reopens_running_owned_service_and_shutdown_releases_locks(self):
        owner=SessionOwner(self.data)
        self.assertIsNone(owner.enter())
        app=Workbench(self.data)
        try:
            with Navigator(app,owner=owner) as server:
                worker=Thread(target=server.serve_forever);worker.start()
                try:
                    owner.publish(server)
                    other=SessionOwner(self.data)
                    try:
                        self.assertEqual(other.enter(),server.url)
                    finally:other.close()
                    record=json.loads(protect(owner.path.read_bytes(),decrypt=True))
                    self.assertEqual(record['session'],server.info['session'])
                    request=Request(server.origin+'/api/session/shutdown',data=b'{}',headers={'Content-Type':'application/json','Origin':server.origin,'X-Journey-Control':'forged'})
                    from urllib.error import HTTPError
                    with self.assertRaises(HTTPError) as denial:urlopen(request)
                    self.assertEqual(denial.exception.code,403)
                finally:server.shutdown();worker.join()
        finally:app.close();owner.close()
        next_owner=SessionOwner(self.data)
        self.assertIsNone(next_owner.enter());next_owner.close()
        self.assertTrue((self.data/'navigator-session.lock').exists())

    def test_verified_activation_retries_a_transport_reset_without_acquiring_ownership(self):
        other = SessionOwner(self.data)
        record = {"session": "verified-record"}
        with patch.object(other, '_request', side_effect=[ConnectionResetError('fixture reset'), {"url": "verified-url"}]) as request:
            with patch('journey_navigator.session.sleep') as wait:
                self.assertEqual(other._activate(record), 'verified-url')
        self.assertEqual(request.call_count, 2)
        self.assertEqual(request.call_args_list[0].args, (record, 'activate'))
        wait.assert_called_once_with(.1)
        self.assertFalse(other.owns)

    def test_activation_retries_are_bounded_and_never_ignore_an_identity_denial(self):
        other = SessionOwner(self.data)
        with patch.object(other, '_request', side_effect=ConnectionResetError('fixture reset')):
            with patch('journey_navigator.session.monotonic', side_effect=[0, 9]):
                with self.assertRaisesRegex(ValueError, 'still owns its checkpoint'):
                    other._activate({})
        with patch.object(other, '_request', side_effect=ValueError('session identity mismatch')) as request:
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                other._activate({})
        self.assertEqual(request.call_count, 1)
        self.assertFalse(other.owns)

    def test_legacy_locked_database_yields_clear_recovery_without_removing_lock(self):
        app=Workbench(self.data)
        try:
            result=subprocess.run([sys.executable,'-B','-m','journey_navigator','--no-browser','--data-dir',str(self.data)],
                                  cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('already open',result.stderr)
            self.assertTrue((self.data/'navigator-inspection.lock').exists())
        finally:app.close()


if __name__=='__main__':unittest.main()
