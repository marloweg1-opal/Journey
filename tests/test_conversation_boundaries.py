"""Real Navigator plus loopback-provider fixtures exercise the new trust seams."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from shutil import copyfile
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic, sleep
import unittest
from unittest.mock import patch

from journey_navigator.conversation import LocalModels
from navigator_fixtures import make_link
from test_conversation_providers import CONTEXT, contribution, envelope, ollama_fixture
from tools.demo_carebloom_collection import make_demo
from tools.demo_conversation_integration import converse, import_history, inspect, request, running_navigator, select


class ConversationBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='journey-conversation-boundary-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.collection, self.exports, self.pack = make_demo(self.base / 'Fixture')

    def test_context_guard_runs_after_tags_and_before_first_generation(self):
        with ollama_fixture(chat=lambda body: envelope(body['model'], contribution())) as (port, calls):
            models = LocalModels(port=port)
            result = models.interpret('Inspect the selected folder', CONTEXT, before_send=lambda: False)
            review = models.review('Review these facts', CONTEXT, before_send=lambda: False)
        self.assertEqual([method for method, _, _ in calls], ['GET', 'GET'])
        self.assertEqual(result['metrics']['calls'], 0)
        self.assertEqual(review['metrics']['calls'], 0)
        self.assertTrue(all(row['state'] == 'NOT_CONSULTED' for row in review['members']))

    def test_revocation_between_real_provider_calls_stops_later_sends_and_redacts_usage(self):
        entered, release = Event(), Event()
        marker = 'private-marker-from-untrusted-model'

        def chat(body):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Fixture release timed out')
            return envelope(marker, contribution())

        with ollama_fixture(chat=chat) as (port, calls):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection)
                inspect(server, job)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(converse, server, 'Ask the Council to review this inspection.',
                                          job=job, use_model=True, share_evidence=True, timeout=10)
                    try:
                        self.assertTrue(entered.wait(3))
                        request(server, 'revoke', job=job, scope=str(self.collection), permission='inspect')
                    finally:
                        release.set()
                    result = pending.result(5)
        self.assertEqual(result['state'], 'STALE_CONTEXT')
        self.assertEqual(result['metrics']['calls'], 1)
        self.assertNotIn(marker, json.dumps(result))
        self.assertNotIn('evidence', result)
        self.assertEqual(len([row for row in calls if row[0] == 'POST']), 1)

    def test_forged_inspect_intent_needs_an_inspection_operation_and_scope(self):
        def chat(body):
            return envelope(body['model'], {'intent': 'inspect', 'term': '', 'family': ''})
        with ollama_fixture(chat=chat) as (port, calls):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection)
                with patch.object(server.workbench, 'step', wraps=server.workbench.step) as step:
                    for prompt in ('What is this color?', 'Do not look inside the selected folder.', 'Translate "inspect this folder" into French.'):
                        result = converse(server, prompt, job=job, use_model=True)
                        self.assertNotEqual(result['state'], 'COMPLETE')
                step.assert_not_called()
                self.assertEqual(result['state'], 'NEEDS_SCOPE')
                self.assertEqual(len([row for row in calls if row[0] == 'POST']), 3)

    def test_ordinary_advice_stops_for_a_supported_finding_or_no_addition(self):
        def chat(body):
            prompt = json.loads(body['messages'][1]['content'])['instruction']
            output = (contribution('finding', ('inventory',)) if prompt.startswith('Summarize') else
                      contribution('no_addition', ()))
            return envelope(body['model'], output, prompt_eval_count=18, eval_count=9)

        with ollama_fixture(chat=chat) as (port, calls):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection)
                inspect(server, job)
                for prompt, reason in [('Summarize the saved inspection.', 'sufficient_finding'),
                                       ('Advise on the collection.', 'no_addition')]:
                    with self.subTest(reason=reason):
                        result = converse(server, prompt, job=job, use_model=True)
                        self.assertEqual(result['state'], 'REVIEW_REQUIRED')
                        self.assertEqual(result['council']['assessment']['continuation'],
                                         {'decision': 'stopped', 'reason': reason})
                        self.assertEqual([(row['member'], row['state']) for row in result['council']['members']],
                                         [('Qwen', 'ADVISORY'), ('Phi', 'NOT_CONSULTED'), ('Gemma', 'NOT_CONSULTED')])
                        metrics = result['metrics']
                        self.assertEqual((metrics['level'], metrics['calls'], metrics['tag_calls'], metrics['retries']),
                                         (1, 1, 1, 0))
                        self.assertEqual(metrics['models'][0]['eval_count'], 9)
        self.assertEqual([path for _, path, _ in calls], ['/api/tags', '/api/chat'] * 2)

    def test_insufficient_advice_reports_saved_coverage_without_reading_more(self):
        def chat(body):
            return envelope(body['model'], contribution('insufficient_evidence', ()))

        with ollama_fixture(chat=chat) as (port, calls):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection)
                inspect(server, job)
                import_history(server, job, self.exports, self.pack)
                with patch.object(server.workbench, 'step') as step, \
                        patch.object(server.workbench.history, 'text_search') as search_history:
                    result = converse(server, 'Advise about "CareRail".', job=job, use_model=True)
                    step.assert_not_called()
                    search_history.assert_not_called()
        self.assertEqual(result['metrics']['calls'], 1)
        self.assertEqual([path for _, path, _ in calls], ['/api/tags', '/api/chat'])
        self.assertFalse(result['metrics']['shared_evidence_excerpts'])
        continuation = result['council']['assessment']['continuation']
        self.assertEqual((continuation['decision'], continuation['reason']), ('stopped', 'insufficient_evidence'))
        self.assertIn('Search history', continuation['next_review'])
        self.assertEqual(set(continuation['observation_ids']), {'knowledge', 'inventory'})
        observations = {row['id']: row['value'] for row in result['evidence']}
        self.assertEqual(observations['inventory']['analyzed'], 10)
        self.assertEqual(observations['knowledge']['history_messages'], 3)

    def test_scoped_objection_gets_one_independent_review_on_identical_input(self):
        def chat(body):
            payload = json.loads(body['messages'][1]['content'])
            evidence = payload['context']['evidence']
            if 'CareRail' in payload['instruction']:
                entry = next(row for row in evidence if row['kind'] == 'imported_history_excerpt')
                conclusion = 'The prior "interface layout" points to a different design.'
            else:
                entry = next(row for row in evidence
                             if row['kind'] == 'inspected_asset' and row['value']['status'] == 'analyzed')
                conclusion = f"The digest {entry['value']['sha256']} identifies a different revision."
            kind = 'objection' if body['model'].startswith('qwen') else 'finding'
            output = {**contribution(kind, (entry['id'],)), 'conclusion': conclusion if kind == 'objection'
                      else 'The same record could still fit the current design.'}
            return envelope(body['model'], output, prompt_eval_count=24, eval_count=11)

        with ollama_fixture(chat=chat) as (port, calls):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection)
                inspect(server, job)
                import_history(server, job, self.exports, self.pack)
                for prompt in ('Advise about "CareRail".', 'Advise on the asset revision.'):
                    with self.subTest(prompt=prompt):
                        calls.clear()
                        result = converse(server, prompt, job=job, use_model=True, share_evidence=True)
                        self.assertEqual(result['state'], 'REVIEW_REQUIRED')
                        metrics = result['metrics']
                        self.assertEqual((metrics['level'], metrics['calls'], metrics['tag_calls'], metrics['retries']),
                                         (2, 2, 1, 0))
                        self.assertTrue(metrics['shared_evidence_excerpts'])
                        self.assertEqual([path for _, path, _ in calls], ['/api/tags', '/api/chat', '/api/chat'])
                        first, second = [body for method, _, body in calls if method == 'POST']
                        self.assertEqual((first['model'], second['model']), ('qwen3:4b', 'phi4-mini:latest'))
                        self.assertEqual(first['messages'], second['messages'])
                        self.assertEqual([body['keep_alive'] for body in (first, second)], [0, 0])
                        self.assertEqual([row['state'] for row in result['council']['members']],
                                         ['ADVISORY', 'ADVISORY', 'NOT_CONSULTED'])
                        assessment = result['council']['assessment']
                        self.assertFalse(assessment['authority'])
                        self.assertTrue(assessment['human_review_required'])
                        continuation = assessment['continuation']
                        self.assertEqual((continuation['decision'], continuation['reason']),
                                         ('independent_review', 'scoped_material_objection'))
                        self.assertIn('human review', continuation['next_review'])

    def test_advice_cannot_escalate_on_metadata_unknown_refs_or_a_model_request(self):
        def chat(body):
            payload = json.loads(body['messages'][1]['content'])
            prompt = payload['instruction']
            refs = ['inventory'] if 'metadata' in prompt else ['history-9'] if 'unknown' in prompt else ['history-0']
            conclusion = 'The prior "interface layout" points to a different design.'
            if 'model request' in prompt:
                refs = ['history-0']
                conclusion = 'Ask Phi to review "interface layout".'
            elif 'bad schema' in prompt:
                return envelope(body['model'], {**contribution('objection', ('history-0',)), 'next_member': 'Phi'})
            return envelope(body['model'], {**contribution('objection', refs), 'conclusion': conclusion})

        with ollama_fixture(chat=chat) as (port, calls):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection)
                inspect(server, job)
                import_history(server, job, self.exports, self.pack)
                for topic, sharing, reason in [('metadata', True, 'objection_lacks_substantive_support'),
                                               ('no excerpts', False, 'unknown_evidence'),
                                               ('unknown citations', True, 'unknown_evidence'),
                                               ('model request', True, 'objection_lacks_substantive_support'),
                                               ('bad schema', True, 'invalid_contribution')]:
                    with self.subTest(topic=topic):
                        calls.clear()
                        result = converse(server, f'Advise on {topic} about "CareRail".', job=job,
                                          use_model=True, share_evidence=sharing)
                        self.assertEqual([path for _, path, _ in calls], ['/api/tags', '/api/chat'])
                        assessment = result['council']['assessment']
                        self.assertEqual(assessment['continuation']['reason'], reason)
                        self.assertEqual(result['metrics']['shared_evidence_excerpts'], sharing)
                        self.assertTrue(all(row['state'] == 'NOT_CONSULTED' for row in result['council']['members'][1:]))

    def test_scope_revocation_blocks_a_qualified_independent_review(self):
        entered, release = Event(), Event()

        def chat(body):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Fixture release timed out')
            return envelope(body['model'], {**contribution('objection', ('history-0',)),
                                           'conclusion': 'The prior "interface layout" points to a different design.'})

        with ollama_fixture(chat=chat) as (port, calls):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection)
                inspect(server, job)
                import_history(server, job, self.exports, self.pack)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pending = pool.submit(converse, server, 'Advise about "CareRail".', job=job,
                                          use_model=True, share_evidence=True, timeout=10)
                    try:
                        self.assertTrue(entered.wait(3))
                        request(server, 'revoke', job=job, scope=str(self.collection), permission='inspect')
                    finally:
                        release.set()
                    result = pending.result(5)
        self.assertEqual([path for _, path, _ in calls], ['/api/tags', '/api/chat'])
        self.assertEqual(result['state'], 'STALE_CONTEXT')
        self.assertEqual((result['metrics']['level'], result['metrics']['calls']), (1, 1))
        self.assertNotIn('council', result)
        self.assertNotIn('evidence', result)

    def test_authority_guidance_stays_with_the_human_even_with_a_scoped_objection(self):
        def chat(body):
            return envelope(body['model'], {**contribution('objection', ('history-0',)),
                                           'conclusion': 'The prior "interface layout" points to a different design.'})

        with ollama_fixture(chat=chat) as (port, calls):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection)
                inspect(server, job)
                import_history(server, job, self.exports, self.pack)
                authority = converse(server, 'What permissions do you have?', job=job, use_model=True)
                self.assertEqual(authority['metrics']['calls'], 0)
                self.assertFalse(authority['authority']['source_mutation_via_conversation'])
                self.assertIn('fresh Windows-account approval', authority['authority']['approval'])
                result = converse(server, 'Recommend whether to delete the draft about "CareRail".', job=job,
                                  use_model=True, share_evidence=True)
        self.assertEqual([path for _, path, _ in calls], ['/api/tags', '/api/chat'])
        assessment = result['council']['assessment']
        self.assertFalse(assessment['authority'])
        self.assertTrue(assessment['human_review_required'])
        continuation = assessment['continuation']
        self.assertEqual((continuation['decision'], continuation['reason']), ('stopped', 'human_authority_review'))
        self.assertIn('fresh Windows-account approval', continuation['next_review'])

    def test_held_archives_and_inference_disabled_images_are_not_sent_to_models(self):
        def chat(body):
            return envelope(body['model'], {'kind': 'no_addition', 'conclusion': '', 'evidence_ids': []})
        with ollama_fixture(chat=chat) as (port, calls):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection)
                inspect(server, job)
                import_history(server, job, self.exports, self.pack)
                permitted = converse(server, 'Search history for CareRail', job=job)
                self.assertTrue(permitted['results'])
                self.assertEqual(permitted['history']['indexed_files'], 2)
                self.assertEqual(permitted['history']['unique_messages'], 3)
                self.assertTrue(permitted['history']['last_indexed'])
                protected_image = self.collection / 'Beat Character Sheet.png'
                policy = self.base / 'Policy.sqlite'
                with closing(sqlite3.connect(policy)) as conn, conn:
                    conn.executescript('CREATE TABLE media_source_holds(scope TEXT); CREATE TABLE perception_policy_events(id INTEGER PRIMARY KEY,scope TEXT,mode TEXT,permissions_json TEXT,purposes_json TEXT);')
                    conn.execute('INSERT INTO media_source_holds VALUES(?)', (str(self.exports),))
                    conn.execute('INSERT INTO perception_policy_events VALUES(1,?,?,?,?)',
                                 (str(protected_image), 'SEALED', json.dumps({'inference_permission': False}), '[]'))
                server.workbench.policy.hold_store = policy
                server.workbench.policy.perception_store = policy
                blocked = converse(server, 'Search history for CareRail', job=job)
                self.assertEqual(blocked['results'], [])
                self.assertEqual(blocked['history'], {'indexed_files': 0, 'unique_messages': 0, 'last_indexed': None,
                                                      'text_index': {'indexed_messages': 0, 'truncated_records': 0}})
                coverage = converse(server, 'Show history coverage', job=job)
                self.assertEqual(coverage['history'], blocked['history'])
                knowledge = converse(server, 'What do you know?', job=job)['knowledge']
                self.assertEqual((knowledge['history_state'], knowledge['history_files'], knowledge['history_messages']),
                                 ('no_indexed_history', 0, 0))
                result = converse(server, 'Ask Phi about "CareRail".', job=job, use_model=True, share_evidence=True)
                self.assertEqual(result['state'], 'REVIEW_REQUIRED')
                body = next(body for method, _, body in calls if method == 'POST')
                context = json.loads(body['messages'][-1]['content'])['context']
                serialized = json.dumps(context)
                for hidden in ('interface layout', 'conversations-001.json', 'conversations-002.json',
                               'Corestone is Opalstone', 'incremental', 'monitor', protected_image.name):
                    self.assertNotIn(hidden, json.dumps(blocked))
                    self.assertNotIn(hidden, serialized)
                self.assertEqual(context['knowledge'], knowledge)
                self.assertEqual(next(row['value'] for row in context['evidence'] if row['id'] == 'knowledge'), knowledge)
                self.assertFalse(any(row['kind'] == 'imported_history_excerpt' for row in context['evidence']))

    def test_session_only_duplicate_status_and_unavailable_discovery_are_explicit(self):
        with ollama_fixture(tags=[], chat=None) as (port, _):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection, retain=False)
                for prompt in ('Find duplicates', 'Duplicate status'):
                    self.assertEqual(converse(server, prompt, job=job)['state'], 'NEEDS_CHECKPOINT')
                result = converse(server, 'Show local models', job=job, use_model=True, share_evidence=True)
                self.assertEqual(result['state'], 'UNAVAILABLE')
                self.assertFalse(result['metrics']['shared_evidence_excerpts'])
                self.assertEqual(result['metrics']['calls'], 0)
                self.assertEqual(result['metrics']['tag_calls'], 1)

    def test_held_overlapping_sources_do_not_hide_authorized_history_matches(self):
        def chat(body):
            return envelope(body['model'], contribution('no_addition', ()))

        with ollama_fixture(chat=chat) as (port, calls):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection)
                inspect(server, job)
                import_history(server, job, self.exports, self.pack)
                allowed = self.base / 'approved-history.json'
                copyfile(self.exports / 'conversations-001.json', allowed)
                preview = request(server, 'history-preview', job=job, path=str(allowed))
                request(server, 'history-enqueue', job=job, ticket=preview['ticket'])
                deadline = monotonic() + 5
                while monotonic() < deadline:
                    status = request(server, 'history-status', job=job)
                    if len(status['files']) == 3 and all(row['status'] == 'complete' for row in status['files']):
                        break
                    sleep(.02)
                self.assertEqual(len(status['files']), 3)
                self.assertTrue(all(row['status'] == 'complete' for row in status['files']))
                coverage = converse(server, 'Show history coverage', job=job)['history']
                self.assertEqual((coverage['indexed_files'], coverage['unique_messages']), (3, 3))
                policy = self.base / 'Holds.sqlite'
                with closing(sqlite3.connect(policy)) as conn, conn:
                    conn.execute('CREATE TABLE media_source_holds(scope TEXT)')
                    conn.execute('INSERT INTO media_source_holds VALUES(?)', (str(self.exports),))
                server.workbench.policy.hold_store = policy
                result = converse(server, 'Search history for CareRail', job=job)
                self.assertTrue(result['results'])
                self.assertTrue(all(row['name'] == allowed.name for row in result['results']))
                coverage = result['history']
                self.assertEqual((coverage['indexed_files'], coverage['unique_messages']), (1, 1))
                self.assertEqual(coverage['text_index'], {'indexed_messages': 1, 'truncated_records': 0})
                self.assertNotIn(allowed.name, json.dumps(coverage))
                converse(server, 'Advise on local history coverage.', job=job, use_model=True)
                body = next(body for method, _, body in calls if method == 'POST')
                context = json.loads(body['messages'][-1]['content'])['context']
                self.assertEqual((context['knowledge']['history_files'], context['knowledge']['history_messages']), (1, 1))
                self.assertFalse(any(row['kind'] == 'imported_history_excerpt' for row in context['evidence']))
                self.assertNotIn(allowed.name, json.dumps(context))
                with server.lock:
                    claims = server.workbench.history.find(job, 'render_17')
                self.assertTrue(claims)
                self.assertTrue(all(row['source']['archive'] == allowed.name for row in claims))

    def test_permission_report_distinguishes_invalid_link_grants_from_effective_access(self):
        target = self.base / 'Linked target'
        target.mkdir()
        link = make_link(self.collection / 'External.lnk', target)
        with ollama_fixture(tags=[], chat=None) as (port, _):
            with running_navigator(self.base / 'Checkpoint', LocalModels(port=port)) as server:
                job = select(server, self.collection)
                inspect(server, job)
                with server.lock:
                    row = next(row for row in server.workbench.links(job, 0)['items'] if row['selected'] == str(link))
                    preview = server.workbench.select(None, job_id=job, link_id=row['id'])
                    server.workbench.approve(preview['ticket'])
                policy = self.base / 'Holds.sqlite'
                with closing(sqlite3.connect(policy)) as conn, conn:
                    conn.execute('CREATE TABLE media_source_holds(scope TEXT)')
                    conn.execute('INSERT INTO media_source_holds VALUES(?)', (str(target),))
                server.workbench.policy.hold_store = policy
                result = converse(server, 'What permissions do you have?', job=job)
                linked = next(scope for scope in result['authority']['scopes'] if scope['path'] == str(target))
                self.assertTrue(linked['recorded_inspect'])
                self.assertFalse(linked['effective_inspect'])
                self.assertEqual(linked['inspect'], 0)


if __name__ == '__main__':
    unittest.main()
