"""Native desktop surface for the folder planner."""

from pathlib import Path, PurePosixPath
from queue import Empty, SimpleQueue
from threading import Thread
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from journey_planner import VERSION
from journey_planner.catalog import DECISIONS, MAX_ENTRIES, MAX_SCAN_SECONDS, absolute_path, scan_folder
from journey_planner.plan_file import PLAN_SUFFIX, coverage_notes, export_plan, open_plan, save_plan


def short_folder(path):
    parts = path.parent.parts
    if not parts:
        return "Source folder"
    return f"…\\{parts[-1]}" if len(parts) > 1 else parts[0]


def show_text(widget, value):
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", value.encode("utf-8", errors="backslashreplace").decode("utf-8"))
    widget.configure(state="disabled")


class Desktop:
    def __init__(self, root, *, primary=None):
        self.root = root
        self.primary = primary
        self.focused_windows = []
        self.plan = None
        self.saved_path = None
        self.revision = None
        self.dirty = False
        self.scanning = False
        self.snapshot = False
        self.rows = {}
        self.previews = {}
        self.search_timer = None
        self.scan_timer = None
        self.search = tk.StringVar(root)
        self.source = tk.StringVar(root, value="Choose a folder to start, or open a saved plan.")
        self.scan_counts = tk.StringVar(root, value="Inspect names, sizes, and timestamps.")
        self.coverage = tk.StringVar(root)
        self.selection = tk.StringVar(root)
        self.status = tk.StringVar(root, value="Ready")
        self.root.title("Journey | Focused Folder Planner" if primary else "Journey | Folder Planner")
        self.root.geometry("1120x720")
        self.root.minsize(850, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.build()
        self.search.trace_add("write", self.schedule_filter)
        self.root.bind("<Control-o>", lambda _event: self.open())
        self.root.bind("<Control-s>", lambda _event: self.save())
        self.root.bind("<Control-f>", lambda _event: self.search_field.focus_set())
        self.refresh()
        self.choose_button.focus_set()

    def build(self):
        header = tk.Frame(self.root, background="#142C33", padx=22, pady=14)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="Journey", background="#142C33", foreground="#FFFFFF",
                 font=("Segoe UI", 24, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(header, text=f"FOLDER PLANNER  /  {VERSION}", background="#142C33", foreground="#B5E8DC",
                 font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="w")
        tk.Label(header, text="SOURCE FOLDER IS READ-ONLY", background="#24484B", foreground="#ECFFF9",
                 padx=11, pady=6, font=("Segoe UI", 9, "bold")).grid(row=0, column=1, rowspan=2, sticky="e")

        body = ttk.Frame(self.root, padding=(20, 12, 20, 8))
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(5, weight=1)
        actions = ttk.Frame(body)
        actions.grid(row=0, column=0, sticky="ew")
        self.choose_button = ttk.Button(actions, text="Choose folder…", command=self.choose_folder)
        self.open_button = ttk.Button(actions, text="Open plan…", command=self.open)
        self.save_button = ttk.Button(actions, text="Save plan", command=self.save)
        self.copy_button = ttk.Button(actions, text="Save a copy…", command=lambda: self.save(copy=True))
        self.export_button = ttk.Button(actions, text="Export checklist…", command=self.export)
        for button in (self.choose_button, self.open_button, self.save_button, self.copy_button, self.export_button):
            button.pack(side="left", padx=(0, 8))
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=105)

        ttk.Label(body, textvariable=self.source, font=("Segoe UI", 10, "bold"), wraplength=790).grid(
            row=1, column=0, sticky="w", pady=(10, 2)
        )
        scan = ttk.Frame(body)
        scan.grid(row=2, column=0, sticky="ew", pady=(2, 1))
        ttk.Label(scan, textvariable=self.scan_counts).pack(side="left")
        self.focus_button = ttk.Button(scan, text="Scan subfolder…", command=self.focus_subfolder)
        self.focus_button.pack(side="right")
        self.details_button = ttk.Button(scan, text="Scan details…", command=self.scan_details)
        self.details_button.pack(side="right", padx=(0, 6))
        ttk.Label(body, textvariable=self.coverage, wraplength=790).grid(row=3, column=0, sticky="w")

        filters = ttk.Frame(body)
        filters.grid(row=4, column=0, sticky="ew", pady=(10, 6))
        ttk.Label(filters, text="Find files").pack(side="left", padx=(0, 5))
        self.search_field = ttk.Entry(filters, textvariable=self.search, width=24)
        self.search_field.pack(side="left", padx=(0, 15))
        ttk.Label(filters, text="Show").pack(side="left", padx=(0, 5))
        self.filter = ttk.Combobox(filters, state="readonly", width=19)
        self.filter.pack(side="left", padx=(0, 15))
        self.filter.bind("<<ComboboxSelected>>", lambda _event: self.draw_rows())
        ttk.Label(filters, text="New collection").pack(side="left", padx=(0, 5))
        self.new_collection = ttk.Entry(filters, width=18)
        self.new_collection.pack(side="left", padx=(0, 5))
        self.new_collection.bind("<Return>", lambda _event: self.create_collection())
        self.create_button = ttk.Button(filters, text="Create", width=15, command=self.create_collection)
        self.create_button.pack(side="left")

        table = ttk.Frame(body)
        table.grid(row=5, column=0, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        columns = ("source", "folder", "collection", "target", "decision", "note")
        self.table = ttk.Treeview(table, columns=columns, show="headings", selectmode="extended")
        self.table.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(table, orient="vertical", command=self.table.yview)
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.table.xview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        for key, label, width, minimum in (
            ("source", "Filename", 240, 145), ("folder", "From folder", 128, 90),
            ("collection", "Collection", 120, 90), ("target", "Proposed destination", 325, 185),
            ("decision", "Decision", 72, 65), ("note", "Preview", 124, 104),
        ):
            self.table.heading(key, text=label, anchor="w")
            self.table.column(key, width=width, minwidth=minimum, stretch=key in ("source", "target"), anchor="w")
        self.table.tag_configure("blocked", foreground="#8C3218")
        self.table.bind("<<TreeviewSelect>>", lambda _event: self.update_selection())

        review = ttk.LabelFrame(body, text="Review selected files", padding=(9, 6, 9, 7))
        review.grid(row=6, column=0, sticky="ew", pady=(8, 5))
        ttk.Label(review, textvariable=self.selection, wraplength=780).pack(anchor="w", pady=(0, 4))
        paths = ttk.Frame(review)
        paths.pack(fill="x", pady=(0, 6))
        self.paths = tk.Text(paths, height=3, width=1, wrap="char", state="disabled", font="TkDefaultFont", padx=5)
        self.paths.pack(side="left", fill="x", expand=True)
        path_scroll = ttk.Scrollbar(paths, orient="vertical", command=self.paths.yview)
        path_scroll.pack(side="right", fill="y")
        self.paths.configure(yscrollcommand=path_scroll.set)
        assignment = ttk.Frame(review)
        assignment.pack(fill="x", pady=(0, 5))
        ttk.Label(assignment, text="Collection").pack(side="left", padx=(0, 5))
        self.collection = ttk.Combobox(assignment, state="readonly", width=21)
        self.collection.pack(side="left", padx=(0, 5))
        self.assign_button = ttk.Button(assignment, text="Assign selected", command=self.assign)
        self.assign_button.pack(side="left", padx=(0, 14))
        ttk.Label(assignment, text="Proposed name").pack(side="left", padx=(0, 5))
        self.name = ttk.Entry(assignment, width=26)
        self.name.pack(side="left", padx=(0, 5))
        self.name.bind("<Return>", lambda _event: self.rename())
        self.rename_button = ttk.Button(assignment, text="Set name", command=self.rename)
        self.rename_button.pack(side="left")
        decisions = ttk.Frame(review)
        decisions.pack(fill="x")
        ttk.Label(decisions, text="Decision").pack(side="left", padx=(0, 8))
        self.decision_buttons = []
        for decision, label in zip(DECISIONS, ("Review later", "Include in checklist", "Keep in place")):
            button = ttk.Button(decisions, text=label, command=lambda value=decision: self.decide(value))
            button.pack(side="left", padx=(0, 5))
            self.decision_buttons.append(button)
        ttk.Label(body, textvariable=self.status, wraplength=790).grid(row=7, column=0, sticky="w")

    @staticmethod
    def enabled(widgets, enabled):
        for widget in widgets:
            widget.state(("!disabled",) if enabled else ("disabled",))

    def refresh(self):
        active = self.plan is not None and not self.scanning
        self.enabled((self.choose_button, self.open_button), not self.scanning)
        self.enabled((self.save_button, self.export_button, self.search_field,
                      self.filter, self.new_collection, self.create_button, self.focus_button, self.details_button), active)
        self.enabled((self.copy_button,), active and self.saved_path is not None)
        if self.plan:
            plan = self.plan
            mode = "Saved snapshot" if self.snapshot else ("Focused scan" if plan.protected_root else "Inspected folder")
            self.source.set(f"{mode}  ·  {plan.root}")
            self.scan_counts.set(f"{len(plan.files):,} files found  ·  {len(plan.gaps):,} skipped paths"
                                 f"  ·  {len(plan.collections):,} collections")
            if plan.limited:
                self.coverage.set(f"{plan.scan_limit} Use Scan subfolder to inspect a smaller area.")
            elif plan.gaps:
                self.coverage.set("Open Scan details to see what was skipped and why.")
            else:
                self.coverage.set("")
        collections = self.plan.collections if self.plan else []
        for widget, prefix in ((self.filter, ["All files", "Unassigned"]), (self.collection, ["Unassigned"])):
            previous = widget.current()
            values = prefix + [f"Collection · {name}" for name in collections]
            widget.configure(values=values)
            widget.current(max(0, min(previous, len(values) - 1)))
        self.previews = self.plan.proposals() if self.plan else {}
        self.draw_rows()

    def schedule_filter(self, *_args):
        if self.search_timer is not None:
            self.root.after_cancel(self.search_timer)
        self.search_timer = self.root.after(180, self.draw_rows)

    def draw_rows(self):
        if self.search_timer is not None:
            self.root.after_cancel(self.search_timer)
            self.search_timer = None
        selected = set(self.selected())
        top = self.table.yview()[0]
        children = self.table.get_children()
        if children:
            self.table.delete(*children)
        self.rows.clear()
        if self.plan:
            query = self.search.get().casefold().strip().replace("\\", "/")
            index = self.filter.current()
            selection = []
            for path, item in self.plan.files.items():
                proposal = self.previews[path]
                if index == 1 and item.collection:
                    continue
                if index >= 2 and item.collection != self.plan.collections[index - 2]:
                    continue
                if query and query not in f"{path} {item.collection} {proposal.destination}".casefold():
                    continue
                source, target = PurePosixPath(path), PurePosixPath(proposal.destination)
                preview = proposal.change
                if proposal.blocker:
                    preview = "Scan incomplete" if self.plan.limited else "Needs review"
                row = self.table.insert("", "end", values=(
                    source.name, short_folder(source), item.collection, f"{target.name}  →  {short_folder(target)}",
                    item.decision, preview,
                ), tags=("blocked",) if proposal.blocker else ())
                self.rows[row] = path
                if path in selected:
                    selection.append(row)
            if selection:
                self.table.selection_set(selection)
            self.table.yview_moveto(top)
        self.update_selection()

    def selected(self):
        return [self.rows[row] for row in self.table.selection() if row in self.rows]

    def update_selection(self):
        paths = self.selected() if not self.scanning else []
        one = len(paths) == 1
        self.create_button.configure(text="Create & assign" if paths else "Create")
        self.enabled((self.assign_button, self.collection, *self.decision_buttons), bool(paths))
        self.name.state(("!disabled",))
        self.name.delete(0, "end")
        self.enabled((self.name, self.rename_button), one)
        details = ""
        if one:
            path = paths[0]
            item, proposal = self.plan.files[path], self.previews[path]
            self.name.insert(0, item.name)
            note = proposal.blocker or proposal.change
            self.selection.set(f"{item.size:,} bytes  ·  Decision {item.decision}  ·  {note}")
            root = Path(self.plan.root)
            details = f"Original     {root / path}\nProposed   {root / proposal.destination}"
        elif paths:
            self.selection.set(f"{len(paths):,} files selected. Create a collection above or assign an existing one below.")
        elif self.plan and not self.rows:
            self.selection.set("No files match this view." if self.plan.files else "No regular files were found in this scan.")
        elif self.plan and not self.plan.collections:
            self.selection.set("First collection? Select related files with Ctrl or Shift, name the group above, then choose Create & assign.")
        else:
            self.selection.set("Select a file to review its proposal. Use Ctrl or Shift to select several.")
        show_text(self.paths, details)

    def change(self, message):
        self.dirty = True
        self.status.set(f"{message}  ·  Unsaved changes")
        self.refresh()

    def show_error(self, title, error):
        messagebox.showerror(title, str(error), parent=self.root)

    def leave_plan(self):
        if not self.dirty:
            return True
        answer = messagebox.askyesnocancel("Unsaved plan", "Save this plan before leaving it?", parent=self.root)
        return answer is False or (answer is True and self.save())

    def replace_plan(self, plan, path=None, revision=None):
        self.plan, self.saved_path, self.revision = plan, path, revision
        self.snapshot = path is not None
        self.dirty = path is None
        self.table.selection_remove(*self.table.selection())
        self.table.yview_moveto(0)
        self.search.set("")
        self.filter.current(0)
        self.collection.current(0)
        self.status.set("Opened saved decisions." if path else "Ready to group files and review proposals.")
        self.refresh()

    def choose_folder(self):
        if self.scanning:
            return
        folder = filedialog.askdirectory(parent=self.root, title="Choose a folder to inspect", mustexist=True)
        if not folder or not self.leave_plan():
            return
        self.start_scan(folder)

    def focus_subfolder(self):
        if self.scanning or not self.plan:
            return
        root = Path(self.plan.root)
        folder = filedialog.askdirectory(parent=self.root, title="Choose a subfolder for a focused scan",
                                         initialdir=root, mustexist=True)
        if not folder:
            return
        try:
            path = absolute_path(folder)
            if path == root or not path.is_relative_to(root):
                raise ValueError(f"Choose a subfolder inside {root}.")
        except ValueError as error:
            self.show_error("Could not focus the scan", error)
            return
        self.start_scan(path, protected_root=self.plan.protected_root or self.plan.root)

    def scan_details(self):
        if self.scanning or not self.plan:
            return
        window = tk.Toplevel(self.root)
        window.title("Journey | Scan details")
        window.transient(self.root)
        window.geometry("740x440")
        window.minsize(460, 260)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        details = tk.Text(window, wrap="char", font="TkDefaultFont", padx=10, pady=10)
        details.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=(10, 0))
        scrollbar = ttk.Scrollbar(window, command=details.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=(10, 0))
        details.configure(yscrollcommand=scrollbar.set)
        notes = [self.plan.root, "", f"Each scan has a budget of {MAX_ENTRIES:,} entries or {MAX_SCAN_SECONDS} seconds.",
                 "Files, folders, and skipped entries count toward the entry limit.", "", *coverage_notes(self.plan)]
        if self.plan.protected_root:
            notes.extend(["", "Save plans and checklists outside the original inspected folder.", self.plan.protected_root])
        show_text(details, "\n".join(notes))
        close_button = ttk.Button(window, text="Close", command=window.destroy)
        close_button.grid(row=1, column=0, columnspan=2, sticky="e", padx=10, pady=10)
        window.bind("<Escape>", lambda _event: window.destroy())
        window.grab_set()
        close_button.focus_set()

    def start_scan(self, folder, *, protected_root=""):
        self.scanning = True
        self.status.set(f"Inspecting names and metadata  ·  Up to {MAX_ENTRIES:,} entries or {MAX_SCAN_SECONDS} seconds")
        self.progress.pack(side="right")
        self.progress.start()
        self.refresh()
        results = SimpleQueue()

        def run_scan():
            try:
                results.put(scan_folder(folder, protected_root=protected_root))
            except (OSError, ValueError) as error:
                results.put(error)

        Thread(target=run_scan, daemon=True).start()

        def complete():
            try:
                result = results.get_nowait()
            except Empty:
                self.scan_timer = self.root.after(60, complete)
                return
            self.scan_timer = None
            self.scanning = False
            self.progress.stop()
            self.progress.pack_forget()
            if isinstance(result, Exception):
                self.status.set("Folder inspection stopped.")
                self.refresh()
                self.show_error("Could not inspect folder", result)
            elif protected_root:
                self.status.set("Focused scan opened in a separate window.")
                self.refresh()
                primary = self.primary or self
                focused = Desktop(tk.Toplevel(primary.root), primary=primary)
                primary.focused_windows.append(focused)
                focused.replace_plan(result)
                focused.status.set("Your broader plan is still open. Save this focused plan separately.")
                focused.table.focus_set()
            else:
                self.replace_plan(result)
                self.table.focus_set()

        self.scan_timer = self.root.after(60, complete)

    def open(self):
        if self.scanning:
            return
        path = filedialog.askopenfilename(parent=self.root, title="Open a Journey plan",
                                          filetypes=[("Journey plans", f"*{PLAN_SUFFIX}")])
        if not path or not self.leave_plan():
            return
        try:
            plan, revision = open_plan(Path(path))
        except (OSError, ValueError) as error:
            self.show_error("Could not open plan", error)
            return
        self.replace_plan(plan, Path(path), revision)
        self.table.focus_set()

    def save(self, *, copy=False):
        if self.scanning or not self.plan:
            return False
        path, expected = self.saved_path, self.revision
        if copy or path is None:
            path = filedialog.asksaveasfilename(
                parent=self.root, title="Save Journey plan outside the inspected folder",
                initialfile=f"Folder plan{PLAN_SUFFIX}", defaultextension=PLAN_SUFFIX,
                filetypes=[("Journey plan", f"*{PLAN_SUFFIX}")],
            )
            if not path:
                return False
            path, expected = Path(path), None
        try:
            revision = save_plan(self.plan, path, expected=expected)
        except (OSError, ValueError) as error:
            self.show_error("Could not save plan", error)
            return False
        self.saved_path, self.revision, self.dirty = path, revision, False
        self.enabled((self.copy_button,), True)
        self.status.set(f"Saved plan  ·  {path}")
        return True

    def export(self):
        if self.scanning or not self.plan:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export a checklist outside the inspected folder",
            initialfile="Journey checklist.txt", defaultextension=".txt", filetypes=[("Text checklist", "*.txt")],
        )
        if not path:
            return
        try:
            export_plan(self.plan, Path(path))
        except (OSError, ValueError) as error:
            self.show_error("Could not export checklist", error)
            return
        self.status.set(f"Exported checklist  ·  {path}")

    def create_collection(self):
        if self.scanning or not self.plan:
            return
        try:
            name = self.plan.add_collection(self.new_collection.get())
        except ValueError as error:
            self.show_error("Could not create collection", error)
            return
        self.new_collection.delete(0, "end")
        paths = self.selected()
        self.plan.assign(paths, name)
        message = f"Created {name} and assigned {len(paths):,} files" if paths else f"Created {name}"
        self.change(message)
        self.collection.current(len(self.plan.collections))

    def assign(self):
        if self.scanning or not self.plan:
            return
        index = self.collection.current()
        name = self.plan.collections[index - 1] if index > 0 else ""
        if self.plan.assign(self.selected(), name):
            self.change(f"Assigned selected files to {name}" if name else "Removed collection assignment")

    def rename(self):
        paths = self.selected()
        if self.scanning or len(paths) != 1:
            return
        try:
            if self.plan.rename(paths[0], self.name.get()):
                self.change("Updated proposed name")
        except ValueError as error:
            self.show_error("Could not use proposed name", error)

    def decide(self, decision):
        if self.scanning or not self.plan:
            return
        changed = False
        for path in self.selected():
            item = self.plan.files[path]
            if item.decision != decision:
                item.decision = decision
                changed = True
        if changed:
            self.change(f"Recorded decision · {decision}")

    def close(self):
        if not self.leave_plan():
            return
        if any(not window.leave_plan() for window in self.focused_windows):
            return
        for window in [*self.focused_windows, self]:
            for timer in (window.scan_timer, window.search_timer):
                if timer is not None:
                    window.root.after_cancel(timer)
        if self.primary:
            self.primary.focused_windows.remove(self)
        self.root.destroy()


def configure_runtime():
    tcl = Path(sys.executable).parent / "tcl"
    if (tcl / "tcl9.0" / "init.tcl").is_file() and (tcl / "tk9.0" / "tk.tcl").is_file():
        os.environ["TCL_LIBRARY"] = str(tcl / "tcl9.0")
        os.environ["TK_LIBRARY"] = str(tcl / "tk9.0")


def main():
    configure_runtime()
    root = tk.Tk()
    icon = Path(__file__).resolve().parent.parent / "assets" / "journey.ico"
    if icon.is_file():
        try:
            root.iconbitmap(str(icon))
        except tk.TclError:
            pass
    Desktop(root)
    root.mainloop()
