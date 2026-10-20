import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.perception_policy import effective_policy, set_policy, semantic_gateway
from core.recovery_domain import Effort, RecoveryAuthority, recover_derivative, observe
from core.media_recovery import video_proof, exact_groups, stable_hash


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:')
    def tearDown(self):
        self.conn.close()

    def test_unknown_is_structural_only_and_does_not_open_content(self):
        reader,provider=Mock(),Mock()
        with self.assertRaises(PermissionError):
            semantic_gateway(self.conn,r'D:\Personal\photo.jpg','identify',reader,provider)
        reader.assert_not_called()
        provider.assert_not_called()
        self.assertEqual(effective_policy(self.conn,r'D:\Personal')['mode'],'SEALED')

    def test_inheritance_child_override_and_sibling_boundary(self):
        set_policy(self.conn,r'D:\Personal','SEALED',reason='source provenance')
        set_policy(self.conn,r'D:\Personal\Project','OPEN',reason='explicit child override')
        self.assertEqual(effective_policy(self.conn,r'D:\Personal\other\a.jpg')['mode'],'SEALED')
        self.assertEqual(effective_policy(self.conn,r'd:\PERSONAL\Project\a.jpg')['inspection_permission'],'SEMANTIC_ALLOWED')
        self.assertEqual(effective_policy(self.conn,r'D:\Personalized\a.jpg')['version'],0)
        self.assertFalse(effective_policy(self.conn,r'D:\Personal\Project')['learning_permission'])

    def test_limited_purpose_and_separate_permissions(self):
        set_policy(self.conn,r'D:\Media','LIMITED',reason='explicit purpose',purposes=['caption'],retention=True)
        denied=effective_policy(self.conn,r'D:\Media\a.jpg',purpose='recognize')
        allowed=effective_policy(self.conn,r'D:\Media\a.jpg',purpose='caption')
        self.assertEqual(denied['inspection_permission'],'STRUCTURAL_ONLY')
        self.assertFalse(denied['semantic_retention_permission'])
        self.assertTrue(allowed['semantic_retention_permission'])
        self.assertFalse(allowed['learning_permission'])

    def test_open_does_not_enable_a_provider(self):
        set_policy(self.conn,r'D:\Media','OPEN',reason='fixture')
        reader=Mock()
        with self.assertRaises(PermissionError):
            semantic_gateway(self.conn,r'D:\Media\a.jpg',None,reader,Mock())
        reader.assert_not_called()

    def test_invalid_policy_combinations_rejected(self):
        for mode,options in [('LIMITED',{}),('SEALED',{'learning':True}),('SEALED',{'retention':True})]:
            with self.subTest(mode=mode,options=options),self.assertRaises(ValueError):
                set_policy(self.conn,r'D:\Media',mode,reason='fixture',**options)

    def test_policy_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'privacy.sqlite'
            conn=sqlite3.connect(path)
            set_policy(conn,r'D:\Media','SEALED',reason='registered recovery source',source_id='fixture-source')
            conn.close()
            conn=sqlite3.connect(path)
            try:
                self.assertEqual(effective_policy(conn,r'D:\Media\child')['source_id'],'fixture-source')
            finally:
                conn.close()

    def test_bridge_rejects_missing_scope_and_unconfirmed_changes(self):
        from mini_ark_server import run_action
        for payload,expected in [({},400),({'path':r'D:\Media','mode':'OPEN'},409)]:
            with patch('mini_ark_server._connect',return_value=sqlite3.connect(':memory:')):
                result,status=run_action('perception-policy-set',payload)
            self.assertEqual(status,expected)
            self.assertFalse(result['ok'])


class RecoveryDomainTests(unittest.TestCase):
    def test_exit_success_does_not_establish_video_usability(self):
        self.assertEqual(video_proof({},[0,0,0])['state'],'NEEDS_DIAGNOSIS')
        probe={'format':{'format_name':'mov','duration':'12'},'streams':[{'codec_type':'video','codec_name':'h264'}]}
        self.assertEqual(video_proof(probe,[0,0,0])['state'],'NEEDS_DIAGNOSIS')
        self.assertEqual(video_proof(probe,[{'exit_code':0,'frames':0}]*3)['state'],'NEEDS_DIAGNOSIS')
        result=video_proof(probe,[{'exit_code':0,'frames':1}]*3)
        self.assertEqual(result['state'],'SAMPLE_DECODABLE')
        self.assertFalse(result['usable'])
        self.assertEqual(video_proof(probe,[0,1,0])['state'],'NEEDS_DIAGNOSIS')

    def test_provider_escalates_without_modifying_original(self):
        class Provider:
            name='disposable-fixture'
            levels=(Effort.SAFE_RECONSTRUCTION,Effort.DEEP_RECOVERY)
            def attempt(self,data,level):
                return b'invalid' if level==Effort.SAFE_RECONSTRUCTION else b'usable:'+data
            def prove_usable(self,data):
                return {'usable':data.startswith(b'usable:'),'checks':{'fixture_header':data.startswith(b'usable:')}}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/'original.bin'
            source.write_bytes(b'evidence')
            output=root/'derivatives'
            output.mkdir()
            conn=sqlite3.connect(':memory:')
            try:
                authority=RecoveryAuthority(str(root),Effort.DEEP_RECOVERY,True,'fixture-authority',str(output))
                result=recover_derivative(conn,source,output,Provider(),authority)
                self.assertEqual(result['state'],'VERIFIED')
                self.assertEqual(source.read_bytes(),b'evidence')
                self.assertEqual(Path(result['output']).read_bytes(),b'usable:evidence')
                self.assertEqual(conn.execute('SELECT state FROM recovery_attempts ORDER BY id').fetchall(),[('REJECTED',),('VERIFIED',)])
                self.assertFalse(result['retirement_authorized'])
            finally:
                conn.close()

    def test_patrol_detection_does_not_authorize_repair(self):
        result=observe('broken.mp4',0)
        self.assertEqual(result['state'],'SUSPECT_EMPTY_MEDIA')
        self.assertFalse(result['repair_authorized'])

    def test_missing_authority_does_not_invoke_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider=Mock()
            conn=sqlite3.connect(':memory:')
            try:
                result=recover_derivative(conn,Path(tmp)/'original',Path(tmp)/'out',provider,RecoveryAuthority(tmp))
                self.assertEqual(result['state'],'AWAITING_DERIVATIVE_AUTHORITY')
                provider.attempt.assert_not_called()
            finally:
                conn.close()

    def test_exact_relationships_require_full_crypto_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            files=[Path(tmp)/name for name in ('a','b','c')]
            for path,data in zip(files,(b'exact',b'exact',b'alternate')):
                path.write_bytes(data)
            records=[{'path':str(path),'hash':stable_hash(path)} for path in files]
            groups=exact_groups(records)
            self.assertEqual(len(groups),1)
            self.assertEqual(len(groups[0]['occurrences']),2)
            self.assertFalse(groups[0]['delete_authorized'])
