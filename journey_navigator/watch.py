"""Session-only, opt-in drift observation. This capability has no action route."""

from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

from core.file_paths import safe_metadata


INTERVAL_SECONDS = 60
ENTRY_BUDGET = 24
CYCLE_SECONDS = .15


class DriftWatch:
    def __init__(self, app):
        self.app = app
        self.target = None
        self.due = 0
        self.report = {"state": "off", "checked": 0, "changes": [], "gaps": 0, "last_check": None}

    def status(self, job=None):
        if self.target and job is not None and self.target[0] != job:
            return {"state": "another inspection is being watched", "enabled": False, "changes": [], "gaps": 0, "checked": 0}
        return self.report | {"enabled": self.target is not None, "interval_seconds": INTERVAL_SECONDS, "entry_budget": ENTRY_BUDGET}

    def enable(self, job):
        row = self.app.job(job)
        self.app._validate_scope(row, row["root"])
        coverage = self.app.summary(job)
        if coverage["pending"] or coverage["pending_folders"]:
            raise ValueError("Finish the scoped inspection before enabling the drift watch.")
        if self.target and self.target[0] != job:
            raise ValueError("Stop the other inspection's drift watch first.")
        self.target = (job, row["root"], row["epoch"])
        self.due = monotonic()
        self.cursor = 0
        self.directory_times = {}
        self.report = {"state": "watching", "checked": 0, "changes": [], "gaps": 0, "last_check": None}
        self._observe(Path(row["root"]))
        return self.status()

    def stop(self, state="off", *, job=None):
        if self.target and (job is None or self.target[0] == job):
            self.target = None
            self.directory_times = {}
            self.report["state"] = state
            if state in ("off", "revoked"):
                self.report["changes"] = []
        return self.status(job)

    def tick(self):
        if self.target is None or monotonic() < self.due:
            return
        self.due = monotonic() + INTERVAL_SECONDS
        job, root, epoch = self.target
        try:
            row = self.app.job(job)
            self.app.policy.refresh()
            self.app._validate_scope(row, root)
        except (OSError, ValueError):
            self.stop("revoked")
            return
        if row["epoch"] != epoch:
            self.stop("inspection refreshed")
            return
        started = monotonic()
        rows = self.app.conn.execute("""SELECT id,path,size,modified FROM files WHERE job=? AND scope=? AND epoch=? AND id>?
            ORDER BY id LIMIT ?""", (job, root, epoch, self.cursor, ENTRY_BUDGET - 1)).fetchall()
        self._observe(Path(root))
        attempts, checked_dirs = 1, {Path(root)}
        for item in rows:
            if attempts >= ENTRY_BUDGET or monotonic() - started >= CYCLE_SECONDS:
                break
            path = Path(item["path"])
            self._observe(path, (item["size"], item["modified"]))
            attempts += 1
            self.cursor = item["id"]
            if attempts < ENTRY_BUDGET and path.parent not in checked_dirs and (
                    path.parent in self.directory_times or len(self.directory_times) < 256):
                self._observe(path.parent)
                checked_dirs.add(path.parent)
                attempts += 1
        if not rows:
            self.cursor = 0
        self.report["last_check"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.report["state"] = "changes detected" if self.report["changes"] else "watching"

    def _observe(self, path, prior=None):
        try:
            observed = safe_metadata(path, read_guard=self.app.policy.check)
            if prior is None:
                current = observed.st_mtime_ns
                changed = self.directory_times.setdefault(path, current) != current
            else:
                changed = prior != (observed.st_size, observed.st_mtime_ns)
        except FileNotFoundError:
            changed = True
        except (OSError, ValueError):
            self.report["gaps"] += 1
            return
        self.report["checked"] += 1
        if changed and path.name not in self.report["changes"] and len(self.report["changes"]) < 12:
            self.report["changes"].append(path.name)
