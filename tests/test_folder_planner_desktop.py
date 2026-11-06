"""Drive the actual desktop buttons through a complete disposable workflow."""

import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from journey_planner.desktop import Desktop, configure_runtime


class FolderPlannerDesktopTests(unittest.TestCase):
    def window(self):
        configure_runtime()
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            if os.environ.get("JOURNEY_REQUIRE_DESKTOP") == "1":
                self.fail(f"Desktop is required for this run: {exc}")
            self.skipTest("This run has no graphical desktop.")
        self.addCleanup(self.destroy, root)
        return root, Desktop(root)

    @staticmethod
    def destroy(root):
        try:
            root.destroy()
        except tk.TclError:
            pass

    def select(self, app, paths):
        app.table.selection_set([row for row, path in app.rows.items() if path in paths])
        app.root.update()
        self.assertEqual(set(app.selected()), set(paths))

    def test_first_use_save_close_reopen_and_export(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / "Files with spaces"
            source.mkdir()
            original = source / "Demo__café.txt"
            original.write_text("preserve this", encoding="utf-8")
            reference = source / "Reference.txt"
            reference.touch()
            before = (original.read_bytes(), original.stat().st_mtime_ns)
            project = base / "Demo plan.journey.json"
            report = base / "My checklist.txt"

            root, app = self.window()
            root.update()
            self.assertTrue(app.save_button.instate(("disabled",)))
            with patch("journey_planner.desktop.filedialog.askdirectory", return_value=str(source)):
                app.choose_button.invoke()
            deadline = time.monotonic() + 8
            while app.scanning and time.monotonic() < deadline:
                root.update()
                time.sleep(0.015)
            self.assertFalse(app.scanning)
            self.assertEqual(len(app.rows), 2)
            app.new_collection.insert(0, "Project assets")
            app.create_button.invoke()
            self.select(app, ["Demo__café.txt", "Reference.txt"])
            app.assign_button.invoke()
            self.select(app, ["Demo__café.txt"])
            app.name.delete(0, "end")
            app.name.insert(0, "Café cover.txt")
            app.rename_button.invoke()
            app.decision_buttons[1].invoke()
            self.select(app, ["Reference.txt"])
            app.decision_buttons[2].invoke()
            with patch("journey_planner.desktop.filedialog.asksaveasfilename", return_value=str(project)):
                app.save_button.invoke()
            self.assertTrue(project.is_file())
            self.assertFalse(app.dirty)
            app.close()

            root, reopened = self.window()
            with patch("journey_planner.desktop.filedialog.askopenfilename", return_value=str(project)):
                reopened.open_button.invoke()
            self.assertEqual(reopened.plan.collections, ["Project assets"])
            self.assertEqual(reopened.plan.files["Demo__café.txt"].decision, "Include")
            self.assertEqual(reopened.plan.files["Reference.txt"].decision, "Keep")
            self.assertEqual(reopened.previews["Demo__café.txt"].destination, "Project assets/Café cover.txt")
            with patch("journey_planner.desktop.filedialog.asksaveasfilename", return_value=str(report)):
                reopened.export_button.invoke()
            text = report.read_text(encoding="utf-8")
            self.assertIn("Included changes (1)", text)
            self.assertIn("Keep in place (1)", text)
            self.assertEqual({path.name for path in source.iterdir()}, {original.name, reference.name})
            self.assertEqual((original.read_bytes(), original.stat().st_mtime_ns), before)
            reopened.close()
