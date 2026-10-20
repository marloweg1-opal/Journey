import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.action_evidence import assess_action, REQUIREMENTS
from core.placement import evaluate_placement
from core.classify import classify_path
from core.pruning import propose_prune
from core.apply import plan_apply, execute_apply
from db.database import initialize_schema


class CalibrationTests(unittest.TestCase):
    def test_conflicting_action_evidence_cannot_be_averaged_away(self):
        facts=[{'kind':kind,'verified':True,'receipt':'fixture','source':'operator_review',
                'fingerprint':'a','coverage_complete':True,'unresolved':0} for kind in REQUIREMENTS['MIGRATE']]
        facts.append({'kind':'source_role','supports_action':False})
        self.assertFalse(assess_action('MIGRATE',facts,current_fingerprint='a')['eligible'])

    def test_revoked_approval_blocks_previously_built_plan(self):
        conn=sqlite3.connect(':memory:')
        conn.row_factory=sqlite3.Row
        initialize_schema(conn)
        try:
            conn.execute("INSERT INTO proposals(description,status) VALUES('fixture','superseded')")
            conn.execute("INSERT INTO proposal_items(proposal_id,canonical_path,dest_path,requested_mode) VALUES(1,'source','destination','move')")
            with patch('core.apply.check_operation_magnitude'), patch('core.apply._move_no_replace') as move:
                result=execute_apply(conn,{'to_apply':[{'item_id':1,'action':'move'}]},verbose=False)
                self.assertEqual(result['failed_count'],1)
                move.assert_not_called()
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM action_log').fetchone()[0],0)
        finally: conn.close()

    def test_interrupted_journal_is_not_reported_applied_after_reopen(self):
        from core import journal
        with tempfile.TemporaryDirectory() as tmp:
            database=Path(tmp)/'fixture.sqlite'
            conn=sqlite3.connect(database)
            conn.row_factory=sqlite3.Row
            initialize_schema(conn)
            with patch.object(journal,'check_kill_switch'):
                op=journal.begin_transaction(conn,{'action_type':'file_move','tier':3,'target_path':'fixture','planned_changes':{'dest':'fixture_destination'}},{'path':'fixture'})
            conn.close()
            reopened=sqlite3.connect(database)
            reopened.row_factory=sqlite3.Row
            try:
                self.assertEqual(reopened.execute('SELECT status FROM action_log WHERE id=?',(op,)).fetchone()['status'],'running')
                with patch.object(journal,'check_kill_switch'), patch('builtins.print'):
                    reverse=unittest.mock.Mock()
                    result=journal.undo_operation(reopened,op,reverse)
                    reverse.assert_not_called()
                    self.assertEqual(result['reason'],'operation_requires_recovery_before_undo')
            finally: reopened.close()

    def test_unverified_completion_cannot_claim_success(self):
        from core import journal
        conn=sqlite3.connect(':memory:')
        conn.row_factory=sqlite3.Row
        initialize_schema(conn)
        try:
            with patch.object(journal,'check_kill_switch'), patch('builtins.print'):
                op=journal.begin_transaction(conn,{'action_type':'file_move','tier':3,'target_path':'fixture','planned_changes':{}},{})
                journal.complete_operation(conn,op,{'path':'fixture'},False)
            self.assertEqual(conn.execute('SELECT status FROM action_log').fetchone()[0],'manual_recovery_required')
        finally: conn.close()

    def test_dependency_search_positive_negative_and_budget(self):
        from dependency_fixture import inspect_references
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'skin.ini'
            path.write_text('ImageName=C:\\HEXSEED\\Icons\\moonstone.ico',encoding='utf-8')
            found=inspect_references([r'C:\HEXSEED\Icons\moonstone.ico'],[tmp])
            self.assertEqual(found['references'][0]['match'],'explicit_path')
            self.assertFalse(found['dependency_clearance'])
            no_match=inspect_references([r'C:\other\absent.ico'],[tmp])
            self.assertEqual(no_match['references'],[])
            self.assertFalse(no_match['dependency_clearance'])
            bounded=inspect_references([r'C:\other\absent.ico'],[tmp],max_bytes=1)
            self.assertTrue(bounded['errors'])

    def test_dependency_read_failure_is_uncertainty(self):
        from dependency_fixture import inspect_references
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'skin.ini'
            path.write_text('fixture')
            with patch.object(Path,'open',side_effect=PermissionError('fixture denied')):
                result=inspect_references(['a.png'],[tmp])
            self.assertTrue(result['errors'])
            self.assertFalse(result['dependency_clearance'])

    def test_identity_age_extension_and_empty_are_not_retirement(self):
        for hint in ['identity','age','extension','empty','strange_path','project_affinity']:
            with self.subTest(hint=hint):
                result=assess_action('QUARANTINE',[{'kind':hint,'verified':True,'confidence':1}])
                self.assertFalse(result['eligible'])
                self.assertEqual(result['confidence'],'REVIEW')

    def test_affirmative_action_evidence_is_required_and_version_bound(self):
        for action, requirements in REQUIREMENTS.items():
            facts=[{'kind':kind,'verified':True,'receipt':f'review:{kind}','source':'operator_review',
                    'fingerprint':'current','coverage_complete':True,'unresolved':0,'condition':'explicit_retirement',
                    'owner_decision_receipt':'fixture-owner-decision'} for kind in requirements]
            with self.subTest(action=action):
                self.assertEqual(assess_action(action,facts,current_fingerprint='current',receipt_verifier=lambda fact, fingerprint: True)['confidence'],'HIGH')
                self.assertFalse(assess_action(action,facts[:-1],current_fingerprint='current',receipt_verifier=lambda fact, fingerprint: True)['eligible'])
                self.assertFalse(assess_action(action,facts,current_fingerprint='changed',receipt_verifier=lambda fact, fingerprint: True)['eligible'])

    def test_perception_never_supplies_action_authority(self):
        facts=[{'kind':kind,'verified':True,'receipt':'model','source':'perception','fingerprint':'a'} for kind in REQUIREMENTS['MIGRATE']]
        self.assertFalse(assess_action('MIGRATE',facts,current_fingerprint='a')['eligible'])

    def test_incomplete_dependency_coverage_blocks_high_confidence(self):
        facts=[{'kind':kind,'verified':True,'receipt':'fixture','source':'verified_inspector','fingerprint':'a',
                'coverage_complete':False,'unresolved':0} for kind in REQUIREMENTS['MIGRATE']]
        self.assertIn('dependency_clearance',assess_action('MIGRATE',facts,current_fingerprint='a')['missing'])

    def test_nearest_project_folder_and_token_boundaries(self):
        self.assertEqual(classify_path(r'R:\HEXSEED\Projects\CareBloomOS\image.png')['owner'],'CareBloomOS')
        self.assertNotEqual(classify_path(r'R:\random\notcarebloom.png')['owner'],'CareBloomOS')

    def test_operational_context_precedes_project_target(self):
        result=evaluate_placement(r'R:\Custom\Rainmeter\Skins\CareBloom\a.png')
        self.assertIsNone(result['likely_canonical_placement'])
        self.assertEqual(result['action_assessment']['confidence'],'UNKNOWN')

    def test_legacy_alias_is_not_high_confidence_action(self):
        result=evaluate_placement(r'R:\Downloads2\known.png')
        self.assertEqual(result['state'],'LEGACY_PATH')
        self.assertEqual(result['action_assessment']['confidence'],'REVIEW')

    def test_empty_scaffold_creates_findings_without_quarantine_items(self):
        conn=sqlite3.connect(':memory:')
        conn.row_factory=sqlite3.Row
        initialize_schema(conn)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp)/'Working').mkdir()
                result=propose_prune(conn,tmp)
                self.assertEqual(result['empty_folders_found'],1)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM proposal_items').fetchone()[0],0)
                self.assertEqual(conn.execute('SELECT resolution_strategy FROM stewardship_findings').fetchone()[0],'REVIEW')
        finally: conn.close()

    def test_old_quarantine_approval_and_forged_plan_cannot_bypass_hold(self):
        conn=sqlite3.connect(':memory:')
        conn.row_factory=sqlite3.Row
        initialize_schema(conn)
        try:
            conn.execute("INSERT INTO proposals(description,status) VALUES('empty branch','approved')")
            conn.execute("INSERT INTO proposal_items(proposal_id,canonical_path,requested_mode) VALUES(1,'R:\\Working','quarantine')")
            self.assertEqual(plan_apply(conn,1)['to_apply'],[])
            with patch('core.apply.check_operation_magnitude'), patch('core.apply.quarantine.quarantine_item') as move:
                result=execute_apply(conn,{'to_apply':[{'item_id':1,'action':'quarantine'}]},verbose=False)
                move.assert_not_called()
                self.assertEqual(result['failed_count'],1)
        finally: conn.close()

if __name__=='__main__': unittest.main()
