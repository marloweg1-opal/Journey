"""Drive the actual desktop buttons through a complete disposable workflow."""

import os
from pathlib import Path
import shutil
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from journey_planner.catalog import scan_folder
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

    def wait_for_scan(self, app):
        deadline = time.monotonic() + 8
        while app.scanning and time.monotonic() < deadline:
            app.root.update()
            time.sleep(0.015)
        self.assertFalse(app.scanning)

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
            self.wait_for_scan(app)
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

    def test_focus_real_project_docs_then_save_close_reopen_and_export(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / "Journey project sample"
            sample = source / "Public Journey documentation"
            shutil.copytree(Path(__file__).resolve().parents[1] / "docs", sample)
            project = base / "Documentation review.journey.json"
            report = base / "Documentation checklist.txt"

            def snapshot():
                return {file.relative_to(source): (file.read_bytes(), file.stat().st_mtime_ns)
                        for file in source.rglob("*") if file.is_file()}

            before = snapshot()
            root, app = self.window()
            with patch("journey_planner.desktop.filedialog.askdirectory", return_value=str(source)), patch(
                "journey_planner.desktop.scan_folder", side_effect=lambda path, **kw: scan_folder(path, max_entries=4, **kw),
            ):
                app.choose_button.invoke()
                self.wait_for_scan(app)
            self.assertIn("4-entry limit", app.coverage.get())
            app.details_button.invoke()
            details_window = next(widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel))
            details = next(widget for widget in details_window.winfo_children() if isinstance(widget, tk.Text))
            self.assertIn("Unvisited entries beyond the limit", details.get("1.0", "end"))
            details_window.destroy()

            app.new_collection.insert(0, "Broader triage")
            app.create_button.invoke()
            with patch("journey_planner.desktop.filedialog.askdirectory", return_value=str(sample)) as picker:
                app.focus_button.invoke()
                self.wait_for_scan(app)
            self.assertEqual(Path(picker.call_args.kwargs["initialdir"]), source)
            focused, = app.focused_windows
            self.assertTrue(app.dirty)
            self.assertEqual(app.plan.collections, ["Broader triage"])
            self.assertFalse(focused.plan.limited)
            self.assertEqual(len(focused.rows), len(before))

            preview_path = "images/journey-repository-preview.svg"
            self.select(focused, [preview_path])
            row = focused.table.selection()[0]
            self.assertEqual(focused.table.set(row, "source"), "journey-repository-preview.svg")
            self.assertIn(str(sample / preview_path), focused.paths.get("1.0", "end"))

            walkthrough, guide = "PROJECT_WALKTHROUGH.md", "USER_GUIDE.md"
            self.select(focused, [walkthrough, guide])
            self.assertEqual(focused.create_button.cget("text"), "Create & assign")
            focused.new_collection.insert(0, "Getting started")
            focused.create_button.invoke()
            self.assertEqual(focused.plan.files[guide].collection, "Getting started")
            self.select(focused, [walkthrough])
            focused.name.delete(0, "end")
            focused.name.insert(0, "Journey walkthrough.md")
            focused.rename_button.invoke()
            focused.decision_buttons[1].invoke()
            destination = "Getting started/Journey walkthrough.md"
            self.assertIn(str(sample / destination), focused.paths.get("1.0", "end"))
            self.select(focused, [guide])
            focused.decision_buttons[2].invoke()
            with patch("journey_planner.desktop.filedialog.asksaveasfilename", return_value=str(project)):
                focused.save_button.invoke()
            self.assertTrue(project.is_file())
            focused.close()
            self.assertFalse(app.focused_windows)
            with patch("journey_planner.desktop.messagebox.askyesnocancel", return_value=False):
                app.close()

            _, reopened = self.window()
            with patch("journey_planner.desktop.filedialog.askopenfilename", return_value=str(project)):
                reopened.open_button.invoke()
            self.assertEqual(reopened.plan.collections, ["Getting started"])
            self.assertEqual(reopened.plan.files[guide].decision, "Keep")
            self.assertEqual(reopened.plan.files[walkthrough].decision, "Include")
            self.assertEqual(reopened.previews[walkthrough].destination, destination)
            self.assertEqual(Path(reopened.plan.protected_root), source)
            with patch("journey_planner.desktop.filedialog.asksaveasfilename", return_value=str(report)):
                reopened.export_button.invoke()
            text = report.read_text(encoding="utf-8")
            self.assertIn("Included changes (1)", text)
            self.assertIn(r"Getting started\Journey walkthrough.md", text)
            self.assertIn("Keep in place (1)", text)
            self.assertEqual(snapshot(), before)
            reopened.close()
