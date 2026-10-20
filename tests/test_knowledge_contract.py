from datetime import datetime, timedelta, timezone
from dataclasses import replace
import sqlite3
import unittest
from unittest.mock import Mock

from core.knowledge_contract import (KnowledgeClaim, Need, assess_need, BLOCKERS,
    supersede_inference, usable_claim, knowledge_capability_status)
from core.perception_policy import (set_policy, effective_policy, semantic_gateway,
    ADDITIONAL_PERMISSIONS)


class KnowledgeContractTests(unittest.TestCase):
    def claim(self, **changes):
        now = datetime.now(timezone.utc)
        values = dict(claim_id='fixture-1',subject='synthetic-subject',scope='fixture-context',
                      value='synthetic-private-content',provenance='JOURNEY_INFERENCE',
                      source_ref='fixture-source', observed_at=now-timedelta(minutes=1),
                      expires_at=now+timedelta(hours=1),purpose='fixture-purpose')
        return KnowledgeClaim(**(values | changes))

    def test_blocked_proposal_leaves_need_unresolved(self):
        need = Need('fixture-need','preserve fixture evidence','before intervention',
                    finding_refs=('fixture-finding',),proposal_refs=('blocked-fixture-proposal',))
        result = need.assess({**dict.fromkeys(BLOCKERS, True), 'resources':False})
        self.assertEqual(result['state'],'UNRESOLVED')
        self.assertIn('RESOURCE_BLOCKED',result['blockers'])
        self.assertFalse(result['action_authorized'])

    def test_feasible_plan_does_not_prove_satisfaction(self):
        self.assertEqual(assess_need(dict.fromkeys(BLOCKERS,True))['state'],'UNRESOLVED')
        self.assertEqual(assess_need(dict.fromkeys(BLOCKERS,True),outcome_verified=True,
                                    evidence_refs=['fixture-proof'])['state'],'SATISFIED')
        self.assertEqual(assess_need({},outcome_verified=True,evidence_refs=['claim'])['state'],'UNRESOLVED')

    def test_private_by_default_and_no_content_repr(self):
        claim = self.claim()
        self.assertEqual(claim.sensitivity,'PRIVATE')
        self.assertEqual(claim.portability,'NONTRANSFERABLE')
        for value in ('synthetic-private-content','synthetic-subject','fixture-context','fixture-source'):
            self.assertNotIn(value,repr(claim))

    def test_correction_supersedes_inference_not_history(self):
        old = self.claim()
        correction = self.claim(claim_id='fixture-2',provenance='USER_CORRECTION',status='accepted')
        history,current = supersede_inference(old,correction)
        self.assertEqual(history.status,'superseded')
        self.assertEqual(old.status,'raw')
        self.assertEqual(current.supersedes_event_id,old.claim_id)
        with self.assertRaises(ValueError):
            supersede_inference(old,replace(correction,scope='another-context'))
        with self.assertRaises(ValueError):
            supersede_inference(old,replace(correction,status='raw'))

    def test_stale_rejected_wrong_purpose_or_unpermitted_claim_not_used(self):
        claim = self.claim(status='accepted')
        grants = {'semantic_retention_permission':True,'inference_permission':True}
        self.assertTrue(usable_claim(claim,grants,purpose=claim.purpose,scope=claim.scope))
        self.assertFalse(usable_claim(claim,{},purpose=claim.purpose,scope=claim.scope))
        self.assertFalse(usable_claim(claim,grants,purpose='different',scope=claim.scope))
        self.assertFalse(usable_claim(claim,grants,purpose=claim.purpose,scope=claim.scope,now=claim.expires_at))
        self.assertFalse(usable_claim(claim,grants,purpose=claim.purpose,scope='different'))
        self.assertFalse(usable_claim(claim,grants,purpose=claim.purpose))
        for status in ('raw','rejected','superseded','stale'):
            self.assertFalse(usable_claim(replace(claim,status=status),grants,purpose=claim.purpose,scope=claim.scope))

    def test_no_collectors_storage_export_or_replication_enabled(self):
        state = knowledge_capability_status()
        self.assertEqual(state['discover_mode'],'DISABLED')
        self.assertEqual(state['user_knowledge_storage'],'PROTECTION_NOT_READY')
        self.assertFalse(state['collection_enabled'])
        self.assertFalse(state['export_enabled'])

    def test_retention_bound_required(self):
        with self.assertRaises(ValueError):
            self.claim(expires_at=datetime.now())
        with self.assertRaises(ValueError):
            self.claim(expires_at=datetime.now(timezone.utc)-timedelta(days=1))


class PrivacyPermissionExtensionTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)

    def test_old_policy_gets_no_new_permissions(self):
        set_policy(self.conn,'C:/fixture','OPEN',reason='fixture',retention=True,learning=True)
        policy = effective_policy(self.conn,'C:/fixture/a',purpose='fixture')
        self.assertTrue(policy['learning_permission'])
        self.assertTrue(all(policy[key] is False for key in ADDITIONAL_PERMISSIONS))

    def test_new_grants_are_independent_purpose_bound_and_survive_read(self):
        set_policy(self.conn,'C:/fixture','OPEN',reason='fixture',purposes=['spell'],
                   additional_permissions={'inference_permission':True})
        policy = effective_policy(self.conn,'C:/fixture/a',purpose='spell')
        self.assertTrue(policy['inference_permission'])
        self.assertFalse(policy['learning_permission'])
        self.assertFalse(policy['discover_permission'])
        self.assertFalse(effective_policy(self.conn,'C:/fixture/a',purpose='other')['inference_permission'])

    def test_cloud_denied_before_read_even_with_inspection_granted(self):
        set_policy(self.conn,'C:/fixture','OPEN',reason='fixture')
        read,provider = Mock(),Mock()
        with self.assertRaises(PermissionError):
            semantic_gateway(self.conn,'C:/fixture/a','spell',read,provider,
                             providers_enabled=True,provider_is_external=True)
        read.assert_not_called()
        provider.assert_not_called()

    def test_sealed_or_unscoped_use_cannot_gain_new_permissions(self):
        for mode,purposes in [('SEALED',['spell']),('OPEN',[])]:
            with self.assertRaises(ValueError):
                set_policy(self.conn,'C:/fixture',mode,reason='fixture',purposes=purposes,
                           additional_permissions={'discover_permission':True})
        with self.assertRaises(ValueError):
            set_policy(self.conn,'C:/fixture','OPEN',reason='fixture',purposes=['spell'],
                       additional_permissions={'learning_permission':True})
