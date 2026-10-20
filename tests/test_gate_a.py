import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.patrol import (live_discover, record_policy, scoped_policy, check_authority,
                         minimum_organization, supersede_portal_proposals)
from core.perception import resolve_dimensions
from core.shadow import run_shadow
from core.apply import plan_apply, ProposalNotApproved
from core.placement import evaluate_placement
from db.database import initialize_schema


class GateATests(unittest.TestCase):
    def test_apply_requires_fresh_single_use_preview(self):
        import mini_ark_server as bridge
        bridge.PREVIEW_RECEIPTS.clear()
        with patch.object(bridge, "_proposal_fingerprint", return_value="version1"), patch.object(bridge, "_run_command", return_value={"ok":True}) as command:
            refused, code = bridge.apply_proposal(1,True,True)
            self.assertEqual(code,409)
            command.assert_not_called()
            preview, _ = bridge.apply_proposal(1,False,False)
            token=preview["preview_token"]
            applied, code = bridge.apply_proposal(1,True,True,token)
            self.assertTrue(applied["ok"])
            replay, code=bridge.apply_proposal(1,True,True,token)
            self.assertEqual(code,409)
            self.assertEqual(command.call_count,2)

    def test_changed_preview_is_refused(self):
        import mini_ark_server as bridge
        bridge.PREVIEW_RECEIPTS.clear()
        with patch.object(bridge,"_proposal_fingerprint",side_effect=["old","old","new"]), patch.object(bridge,"_run_command",return_value={"ok":True}) as command:
            preview,_=bridge.apply_proposal(1,False,False)
            result,code=bridge.apply_proposal(1,True,True,preview["preview_token"])
            self.assertEqual(code,409)
            self.assertEqual(command.call_count,1)

    def test_restart_loses_preview_authority(self):
        import mini_ark_server as bridge
        with patch.object(bridge,"_proposal_fingerprint",return_value="old"), patch.object(bridge,"_run_command",return_value={"ok":True}) as command:
            preview,_=bridge.apply_proposal(1,False,False)
            bridge.PREVIEW_RECEIPTS.clear()
            result,code=bridge.apply_proposal(1,True,True,preview["preview_token"])
            self.assertEqual(code,409)
            self.assertEqual(command.call_count,1)

    def test_project_name_does_not_authorize_icon_migration(self):
        result = evaluate_placement(r"C:\HEXSEED\10_ASSETS\HEXSEED_ICONS\ICO\mini_ark.ico")
        self.assertEqual(result["resolution_strategy"], "REVIEW")
        self.assertEqual(result["confidence_dimensions"]["placement"]["confidence"], "Tentative")

    def test_dependent_move_does_not_become_shortcut(self):
        self.conn.execute("INSERT INTO proposals(description,status) VALUES('fixture','approved')")
        self.conn.execute("INSERT INTO proposal_items(proposal_id,canonical_path,dest_path,requested_mode) VALUES(1,?,?, 'move')",(r"R:\fixture\a.png",r"R:\target\a.png"))
        self.conn.execute("INSERT INTO file_dependents(canonical_path,program_name) VALUES(?,'Rainmeter')",(r"R:\fixture\a.png",))
        plan = plan_apply(self.conn,1)
        self.assertEqual(plan["to_apply"],[])
        self.assertEqual(plan["blocked_count"],1)

    def test_partial_run_never_claims_missing_unvisited_files(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as reports:
            for n in range(5):
                (Path(tmp)/f"{n}.txt").write_text("fixture")
            run_shadow(self.conn,scope=tmp,docs_root=reports)
            bounded=run_shadow(self.conn,scope=tmp,docs_root=reports,limit=1)
            self.assertFalse(bounded["comparison"]["absence_inferred"])
            self.assertEqual(bounded["comparison"]["not_observed"],[])

    def test_bridge_missing_column_regression(self):
        import mini_ark_server as bridge
        class ConnectionView:
            def execute(inner,*args): return self.conn.execute(*args)
            def close(inner): pass
        self.conn.execute("INSERT INTO proposals(description) VALUES('fixture')")
        self.conn.execute("INSERT INTO proposal_items(proposal_id,canonical_path,dest_path) VALUES(1,'source','destination')")
        with patch.object(bridge,"_connect",return_value=ConnectionView()):
            self.assertEqual(bridge.proposal_items(1)["items"][0]["target_path"],"destination")

    def test_cancelled_patrol_does_no_work(self):
        import threading
        from core.patrol import run_patrol
        stop=threading.Event()
        stop.set()
        self.assertEqual(run_patrol(self.conn,scope=r"R:\fixture",docs_root="unused",stop=stop),[])

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        initialize_schema(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_unledgered_garden_is_discovered_and_repeat_is_quiet(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as reports:
            root = Path(tmp)
            for name in ["carebloom.png", "notes.txt", "odd%_name.json"]:
                (root / name).write_bytes(name.encode())
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()}
            first = run_shadow(self.conn, scope=tmp, docs_root=reports)
            second = run_shadow(self.conn, scope=tmp, docs_root=reports)
            self.assertEqual(first["files_examined"], 3)
            self.assertEqual(first["evidence_source"], "live_scan")
            self.assertEqual(second["comparison"]["changed"], [])
            self.assertEqual(second["attention_posture"], "SILENT")
            self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir()})
            (root / "notes.txt").write_bytes(b"changed content")
            third = run_shadow(self.conn, scope=tmp, docs_root=reports)
            self.assertEqual(len(third["comparison"]["changed"]), 1)

    def test_budget_and_missing_scope_are_not_empty_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            for n in range(4):
                (Path(tmp) / str(n)).write_text("fixture")
            rows, coverage = live_discover(tmp, max_files=2)
            self.assertEqual(len(rows), 2)
            self.assertFalse(coverage["complete"])
            rows, coverage = live_discover(str(Path(tmp) / "absent"))
            self.assertFalse(coverage["complete"])
            self.assertTrue(coverage["errors"])

    def test_scope_boundary_and_sql_wildcards(self):
        for path in [r"R:\Test_1\x.png", r"R:\Test_10\x.png", r"R:\TestA1\x.png"]:
            self.conn.execute("INSERT INTO files(canonical_path,status) VALUES(?,'present')", (path,))
        with tempfile.TemporaryDirectory() as reports:
            result = run_shadow(self.conn, scope=r"R:\Test_1", docs_root=reports, verify_current=False)
        self.assertEqual(result["files_examined"], 1)

    def test_lifecycle_inheritance_and_revocation(self):
        record_policy(self.conn, kind="lifecycle", scope="R:\\", value="CONSTRUCTION", reason="building")
        record_policy(self.conn, kind="lifecycle", scope=r"R:\Projects\Done", value="STEWARDSHIP", reason="completed")
        self.assertEqual(scoped_policy(self.conn,r"R:\Projects\Done\a", "lifecycle")["value"], "STEWARDSHIP")
        record_policy(self.conn,kind="authority",scope="R:\\",capability="scan",value={"permission":"OBSERVE","constraints":{"count":10}},reason="explicit test grant")
        self.assertEqual(check_authority(self.conn,r"R:\Projects","scan",{"count":11})["permission"], "ASK")
        self.assertEqual(check_authority(self.conn,r"R:\Projects","scan",{"count":3,"managed_mutation":False})["permission"], "OBSERVE")
        self.assertEqual(check_authority(self.conn,r"R:\Projects","scan",{"count":3,"managed_mutation":True})["permission"], "ASK")
        record_policy(self.conn,kind="authority",scope="R:\\",capability="scan",value={"permission":"ASK"},reason="revoked")
        self.assertEqual(check_authority(self.conn,r"R:\Projects","scan",{"count":3})["permission"], "ASK")

    def test_minimum_organization_boundaries(self):
        self.assertFalse(minimum_organization(4,20)["eligible"])
        self.assertFalse(minimum_organization(5,19)["eligible"])
        self.assertTrue(minimum_organization(5,20)["eligible"])
        self.assertFalse(minimum_organization(5,20)["recommend_subfolder"])
        self.assertTrue(minimum_organization(1,2,operational_requirement=True)["recommend_subfolder"])

    def test_old_approval_is_superseded_not_reinterpreted(self):
        self.conn.execute("INSERT INTO proposals(description,status) VALUES('Suggest grouping 12 Video under project-portal reference','approved')")
        self.assertEqual(supersede_portal_proposals(self.conn),[1])
        self.assertEqual(supersede_portal_proposals(self.conn),[])
        with self.assertRaises(ProposalNotApproved):
            plan_apply(self.conn,1)

    def test_canon_beats_similarity_only_unresolved_dimensions_ask(self):
        answer = resolve_dimensions([
            {"dimension":"project","kind":"explicit_canon","value":"HEXSEED","confidence":1},
            {"dimension":"project","kind":"similarity","value":"CareBloomOS","confidence":0.99},
            {"dimension":"role","kind":"perception","value":"wallpaper","confidence":0.97}])
        self.assertEqual(answer["project"]["candidates"][0]["value"],"HEXSEED")
        self.assertEqual(answer["affinity"]["status"],"unresolved")
        self.assertEqual(answer["role"]["status"],"candidate")

    def test_reparse_point_is_not_followed(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            (real / "file.txt").write_text("fixture")
            original = __import__("os").lstat
            def lstat(path):
                if Path(path) == real:
                    from types import SimpleNamespace
                    return SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400)
                return original(path)
            with patch("core.patrol.os.lstat", side_effect=lstat):
                rows, coverage = live_discover(str(real))
            self.assertEqual(rows, [])
            self.assertTrue(coverage["skipped"])


if __name__ == "__main__":
    unittest.main()
