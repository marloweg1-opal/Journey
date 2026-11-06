import json
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from journey_navigator.links import CLASS_ID, Boundaries, UnsupportedLink, resolve_folder, shortcut_path
from journey_navigator.workbench import Workbench
from navigator_fixtures import make_link


class NavigatorInspectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="navigator-links-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / "Source library"
        self.source.mkdir()
        self.app = Workbench(self.base / "Review storage")
        self.addCleanup(self.app.close)

    def finish(self, job):
        for _ in range(200):
            summary = self.app.step(job)
            if not (summary["pending_folders"] or summary["pending"]):
                return summary
        self.fail("Discovery did not finish within its expected batches.")

    def test_native_shortcut_selection_records_target_and_respects_scope(self):
        Image.new("RGB", (50, 60), "purple").save(self.source / "an image.png")
        alias = make_link(self.base / "Source shortcut.lnk", self.source)
        lstat = Path.lstat

        def prevent_target_probe(path):
            if path.is_relative_to(self.source):
                raise AssertionError("The destination was probed before approval.")
            return lstat(path)

        with patch.object(Path, "lstat", prevent_target_probe):
            preview = self.app.select(alias)
        self.assertEqual(preview["status"], "approval_required")
        self.assertEqual(Path(preview["target"]), self.source)
        self.assertEqual(self.app.jobs(), [])
        job = self.app.approve(preview["ticket"])["job"]
        result = self.finish(job)
        self.assertEqual(result["analyzed"], 1)
        recorded, = self.app.links(job, 0)["items"]
        self.assertEqual(Path(recorded["selected"]), alias)
        self.assertEqual(Path(recorded["target"]), self.source)
        self.assertEqual(recorded["kind"], "Windows shortcut" if os.name == "nt" else "symbolic link")
        with self.assertRaisesRegex(ValueError, "expired"):
            self.app.approve(preview["ticket"])

    def test_junction_and_shortcut_share_physical_directory_and_cycles_stop(self):
        first, second = self.source / "First", self.source / "Second"
        first.mkdir()
        second.mkdir()
        Image.new("RGB", (45, 60), "green").save(first / "sample.png")
        make_link(self.source / "First alias.lnk", first)
        make_link(self.source / "First junction", first, "junction")
        make_link(first / "Loop back", self.source, "junction")
        make_link(first / "Second edge", second, "junction")
        make_link(second / "First edge", first, "junction")
        job = self.app.select(self.source)["job"]
        summary = self.finish(job)
        links = self.app.links(job, 0)["items"]
        self.assertEqual(summary["folders"], 3)
        self.assertEqual(summary["analyzed"], 1)
        self.assertGreaterEqual(sum(item["status"] == "already_covered" for item in links), 1)
        self.assertEqual(sum(item["status"] == "cycle" for item in links), 2)
        if os.name == "nt":
            self.assertTrue(any(item["kind"] == "junction" for item in links))

    def test_inaccessible_broken_and_retargeted_links(self):
        gone = self.base / "Missing target"
        gone.mkdir()
        alias = make_link(self.base / "Breakable.lnk", gone)
        gone.rename(self.base / "Different location")
        preview = self.app.select(alias)
        self.assertEqual(self.app.approve(preview["ticket"])["status"], "broken")
        alias = make_link(self.base / "Private.lnk", self.source)
        preview = self.app.select(alias)
        lstat = Path.lstat

        def denied(path):
            if path.is_relative_to(self.source):
                raise PermissionError("Fixture denies access")
            return lstat(path)

        with patch.object(Path, "lstat", denied):
            self.assertEqual(self.app.approve(preview["ticket"])["status"], "inaccessible")
        preview = self.app.select(alias)
        alias.unlink()
        make_link(alias, self.base / "Different location")
        with self.assertRaisesRegex(ValueError, "link changed"):
            self.app.approve(preview["ticket"])
        self.assertEqual(self.app.jobs(), [])

    def test_existing_source_hold_blocks_alias_and_perception_policy_blocks_decode(self):
        blocked = self.source / "Held media"
        blocked.mkdir()
        alias = make_link(self.base / "Held.lnk", blocked)
        store = self.base / "policy.sqlite"
        connection = sqlite3.connect(store)
        connection.executescript("""CREATE TABLE media_source_holds(scope TEXT);
            CREATE TABLE perception_policy_events(id INTEGER PRIMARY KEY,scope TEXT,mode TEXT,permissions_json TEXT,purposes_json TEXT);""")
        connection.execute("INSERT INTO media_source_holds VALUES(?)", (str(blocked),))
        connection.execute("INSERT INTO perception_policy_events VALUES(1,?,?,?,?)", (str(self.source), "SEALED", "{}", "[]"))
        connection.commit()
        connection.close()
        Image.new("RGB", (50, 60), "purple").save(self.source / "sealed.png")
        self.app.policy = Boundaries((self.app.data_dir,), hold_store=store, perception_store=store)
        self.assertEqual(self.app.select(alias)["status"], "protected")
        job = self.app.select(self.source)["job"]
        with patch("journey_navigator.workbench.image_bytes", side_effect=AssertionError("Protected image opened")):
            summary = self.finish(job)
        self.assertEqual(summary["analyzed"], 0)
        self.assertTrue(any("perception policy" in row["reason"] for row in self.app.issues(job, 0)["items"]))

    def test_parser_rejects_unsupported_and_accepts_local_windows_path_records(self):
        path = r"D:\External images\Étoile"
        header = struct.pack("<I", 76) + CLASS_ID + struct.pack("<I", 2) + bytes(52)
        ansi = b"D:\\External images\\Etoile\0"
        unicode = path.encode("utf-16-le") + bytes(2)
        info = struct.pack("<9I", 36 + len(ansi) + 1 + len(unicode) + 2, 36, 1, 0, 36, 0,
                           36 + len(ansi), 37 + len(ansi), 37 + len(ansi) + len(unicode))
        self.assertEqual(shortcut_path(header + info + ansi + b"\0" + unicode + bytes(2)), path)
        relative = r"..\Art\Gallery"
        relative_header = header[:20] + struct.pack("<I", 128 | 8) + header[24:]
        self.assertEqual(shortcut_path(relative_header + struct.pack("<H", len(relative)) + relative.encode("utf-16-le")), relative)
        network = struct.pack("<7I", 28, 28, 2, 0, 0, 0, 0)
        with self.assertRaisesRegex(UnsupportedLink, "Network"):
            shortcut_path(header + network)
        with self.assertRaises(UnsupportedLink):
            shortcut_path(header + info[:12])

    @unittest.skipUnless(os.name == "nt", "Windows drive and shortcut fixture")
    def test_shortcut_to_another_local_drive(self):
        locations = [os.environ.get("RUNNER_TEMP"), os.environ.get("TEMP"), os.environ.get("LOCALAPPDATA")]
        paths = [Path(value).resolve() for value in locations if value and Path(value).is_dir()]
        target_parent = next((path for path in paths if path.drive != self.base.drive), None)
        if target_parent is None:
            self.skipTest("This Windows host has one writable local drive.")
        with tempfile.TemporaryDirectory(dir=target_parent, prefix="navigator-cross-drive-") as directory:
            target = Path(directory).resolve()
            Image.new("RGB", (40, 40)).save(target / "drive image.png")
            shortcut = make_link(self.source / "Other drive.lnk", target)
            pending = self.app.select(shortcut)
            self.assertEqual(pending["status"], "approval_required")
            self.assertNotEqual(Path(pending["target"]).drive, self.base.drive)
            job = self.app.approve(pending["ticket"])["job"]
            self.assertEqual(self.finish(job)["analyzed"], 1)

    @unittest.skipUnless(os.name == "nt", "Windows symbolic-link fixture")
    def test_windows_directory_symlink(self):
        try:
            symlink = make_link(self.base / "Symbolic folder", self.source, "symbolic")
        except OSError as error:
            if getattr(error, "winerror", None) == 1314:
                self.skipTest("This host disallows creating symbolic links.")
            raise
        result = resolve_folder(symlink, self.app.policy, [self.source])
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.hops[0]["kind"], "symbolic link")


if __name__ == "__main__":
    unittest.main()
