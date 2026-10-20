import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


class NavigatorDependencyCoverageTests(unittest.TestCase):
    def test_coverage_formatter_preserves_limits_and_handles_legacy_runs(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node required for Navigator JavaScript fixture')
        html = (Path(__file__).resolve().parents[1] / 'index.html').read_text(encoding='utf-8')
        function = re.search(r'    function patrolCoverage\(run\) \{.*?\n    \}', html, re.S)
        self.assertIsNotNone(function)
        self.assertIn('${esc(patrolCoverage(run))}', html)
        checked = {'path': '<script>fixture</script>', 'reference_method': 'TEXT_MATCHING_ONLY',
                   'structured_parser_supported': False, 'dependency_semantics_complete': False}
        run = {'coverage': {'complete': True}, 'dependency_coverage': {
            'checked': [checked], 'dependency_state': 'UNKNOWN', 'dependency_clearance': False}}
        script = function.group(0) + '\nconsole.log(JSON.stringify([' + \
            'JSON.parse(patrolCoverage(' + json.dumps(run) + ')),' + \
            'JSON.parse(patrolCoverage({})), JSON.parse(patrolCoverage({dependency_coverage:null}))]));'
        result = subprocess.run([node, '-e', script], capture_output=True, text=True,
                                check=True, timeout=10)
        current, legacy, null = json.loads(result.stdout)
        self.assertEqual(current, {'discovery': run['coverage'], 'dependency': run['dependency_coverage']})
        for fallback in (legacy, null):
            self.assertEqual(fallback['dependency']['dependency_state'], 'UNKNOWN')
            self.assertFalse(fallback['dependency']['dependency_clearance'])
            self.assertIsNone(fallback['discovery'])
