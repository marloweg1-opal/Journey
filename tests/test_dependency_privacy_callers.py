"""Check known audit/Shadow wiring without executing managed-source campaigns."""
import ast
import unittest
from pathlib import Path


class DependencyPrivacyCallerTests(unittest.TestCase):
    def test_known_production_callers_supply_registry_connection(self):
        root = Path(__file__).resolve().parents[1]
        callers = ['core/shadow.py']
        # Local campaign scripts are deliberately excluded from public releases.
        callers.extend(relative for relative in ('work/calibration_audit.py',
                       'work/gate_a_continuation_audit.py') if (root / relative).is_file())
        for relative in callers:
            with self.subTest(caller=relative):
                tree = ast.parse((root / relative).read_text(encoding='utf-8-sig'))
                calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Name)
                         and node.func.id == 'inspect_references']
                self.assertTrue(calls)
                for call in calls:
                    privacy = [kw.value for kw in call.keywords if kw.arg == 'privacy_conn']
                    self.assertEqual(len(privacy), 1)
                    self.assertIsInstance(privacy[0], ast.Name)
                    self.assertEqual(privacy[0].id, 'conn')
