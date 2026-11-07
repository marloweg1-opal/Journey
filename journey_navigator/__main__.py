"""Run the existing Navigator shell with an isolated inspection backend."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys
from threading import RLock, Thread, Timer
from urllib.parse import parse_qs, urlsplit
import webbrowser

from journey_navigator.links import ProtectedPath
from journey_navigator.ocr import find_local_ocr
from journey_navigator.patrol import Patrol
from journey_navigator.session import SessionOwner, build_info
from journey_navigator.workbench import Workbench, _prepare_data_dir
from journey_planner.catalog import check_local_drive


MODULE = Path(__file__).resolve().parent
APP = MODULE.parent


def navigator_page():
    page = (APP / "index.html").read_text(encoding="utf-8")
    panel = (MODULE / "inspection.html").read_text(encoding="utf-8")
    panel += (MODULE / "patrol.html").read_text(encoding="utf-8")
    workbench = page.index('      <section class="panel" data-panel="workbench">')
    results = page.index('      <section class="panel" data-panel="results">', workbench)
    page = page[:workbench] + panel + page[results:]
    return (page.replace("</head>", '<link rel="stylesheet" href="/inspection.css"></head>')
            .replace('<span>C:\\mini_ark</span>', '<span>Isolated inspection · local review</span>')
            .replace('<strong>Launch</strong><span>Use focused local utilities</span>', '<strong>Inspect</strong><span>Folders and linked folders</span>', 1)
            .replace('data-select="tools"><strong>Inspect', 'data-select="inspect"><strong>Inspect', 1)
            .replace('Search memory and context', 'Find files in the current review', 1)
            .replace('Task-based help with actions', 'Folder inspection help', 1)
            .replace('Config, ledgers, tests, Git', 'Saved inspections and app controls', 1)
            .replace('Search tools, guide entries, and ARK memory', 'Find inspected files and saved projects', 1)
            .replace('duplicates, migration, kernels, profiles, diagnostics', 'Search your current inspection', 1)
            .replace('    const panels =', '    entries.length = 0;\n    const panels =', 1)
            .replace('    async function bridgeRequest', '''    const launchToken = new URLSearchParams(location.hash.slice(1)).get("session");
    if (launchToken) {
      sessionStorage.setItem("journey-inspection-session", launchToken);
      history.replaceState(null, "", location.pathname);
    }
    async function bridgeRequest''', 1)
            .replace('await fetch(path, options)', '''await fetch(path, {...options, headers: {...options.headers,
          "X-Journey-Session": sessionStorage.getItem("journey-inspection-session") || "",
          "X-Journey-Inspection": sessionStorage.getItem("journey-current-inspection") || ""}})''', 1)
            .replace('    refreshStatus();', '', 1)
            .replace('from Navigator and ARK memory.', 'from this inspection.', 1)
            .replace('</body>', '<script src="/inspection.js"></script><script src="/patrol.js"></script></body>'))


def local_drives():
    if os.name != "nt":
        return [str(Path.home().anchor)]
    import ctypes

    mask = ctypes.windll.kernel32.GetLogicalDrives()
    available = []
    for index in range(26):
        if mask & (1 << index):
            path = Path(f"{chr(65 + index)}:\\")
            try:
                check_local_drive(path)
            except ValueError:
                continue
            available.append(str(path))
    return available


class Navigator(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, workbench, port=0, *, owner=None, approver=None):
        super().__init__(("127.0.0.1", port), Handler)
        self.workbench = workbench
        self.temporary = Workbench(workbench.data_dir, ocr=workbench.ocr, temporary=True)
        self.temporary.policy = workbench.policy
        self.token = secrets.token_urlsafe(32)
        self.lock = RLock()
        self.owner = owner
        self.info = owner.info if owner else build_info()
        self.clients = set()
        self.closing = False
        self.restore_checkpoint = None
        self.patrol = Patrol(workbench, self.lock, approver=approver)
        self.host = f"127.0.0.1:{self.server_address[1]}"
        self.origin = f"http://{self.host}"
        self.static = {"/": ("text/html; charset=utf-8", navigator_page().encode("utf-8")),
                       "/inspection.js": ("text/javascript; charset=utf-8", (MODULE / "inspection.js").read_bytes()),
                       "/inspection.css": ("text/css; charset=utf-8", (MODULE / "inspection.css").read_bytes()),
                       "/patrol.js": ("text/javascript; charset=utf-8", (MODULE / "patrol.js").read_bytes())}

    @property
    def url(self):
        return f"{self.origin}/#session={self.token}"

    def review_store(self, key):
        return self.temporary if isinstance(key, str) and key.startswith("session-") else self.workbench

    def server_close(self):
        super().server_close()
        if hasattr(self, "patrol"):
            self.patrol.close()
        if hasattr(self, "temporary"):
            self.temporary.close()

    def request_close(self):
        self.closing = True
        self.patrol.stop.set()
        self.patrol.wake.set()
        Thread(target=self.shutdown, daemon=True).start()

    def detached(self, client):
        self.clients.discard(client)
        def close_if_unused():
            with self.lock:
                if not self.clients:
                    self.request_close()
        Timer(5, close_if_unused).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        return

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def _reply(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; img-src data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, value, code=200):
        self._reply(code, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=True).encode("utf-8"))

    def _origin_ok(self, *, post=False):
        if self.headers.get("Host") != self.server.host or self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            return False
        origin = self.headers.get("Origin")
        return origin == self.server.origin if post or origin else True

    def _session_ok(self):
        token = self.headers.get("X-Journey-Session", "")
        return token.isascii() and secrets.compare_digest(token, self.server.token)

    def do_GET(self):
        route = urlsplit(self.path)
        if not self._origin_ok():
            return self._json({"error": "Open Journey using its local launcher."}, 403)
        if route.path in self.server.static:
            return self._reply(200, *self.server.static[route.path])
        if route.path == "/api/search" and self._session_ok():
            query = parse_qs(route.query).get("q", [""])[0][:200]
            job = self.headers.get("X-Journey-Inspection", "")
            with self.server.lock:
                try:
                    return self._json({"results": self.server.review_store(job).search(job, query) if job and query else []})
                except (OSError, ValueError) as error:
                    return self._json({"error": str(error)}, 400)
        return self._json({"error": "This resource is unavailable in the inspection candidate."}, 404)

    def do_POST(self):
        route = urlsplit(self.path).path
        if route.startswith('/api/session/'):
            owner = self.server.owner
            supplied = self.headers.get('X-Journey-Control','')
            if not owner or not supplied.isascii() or not self._origin_ok(post=True) or not secrets.compare_digest(supplied,owner.control):
                return self._json({'error':'This session control request could not be authenticated.'},403)
            action=route.removeprefix('/api/session/')
            if action=='shutdown':
                self.server.request_close()
            elif action not in ('status','activate'):
                return self._json({'error':'Unknown session action.'},404)
            return self._json(self.server.info | {'url':self.server.url})
        if not self._origin_ok(post=True) or not self._session_ok():
            return self._json({"error": "This action requires the local Navigator session."}, 403)
        if not route.startswith("/api/inspect/"):
            return self._json({"error": "This candidate exposes inspection actions only."}, 404)
        try:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Use the Navigator interface.")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 64 * 1024:
                raise ValueError("The Navigator request is too large or empty.")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("The Navigator request is invalid.")
            with self.server.lock:
                if self.server.closing:
                    return self._json({'error':'Navigator is closing after its safe checkpoint.'},409)
                result = self._run(route.removeprefix("/api/inspect/"), body)
            return self._json(result)
        except ProtectedPath as error:
            return self._json({"error": str(error)}, 403)
        except sqlite3.Error:
            return self._json({"error": "Journey could not save this review step. Reopen the saved inspection and retry."}, 503)
        except (OSError, ValueError, TypeError, KeyError) as error:
            return self._json({"error": str(error)}, 400)

    def _run(self, action, body):
        job, offset = body.get("job"), body.get("offset", 0)
        app = self.server.review_store(job)
        patrol = self.server.patrol
        destination = body.get('destination')
        if action == 'build':
            return self.server.info
        if action == 'checkpoints':
            from journey_navigator.migrations import checkpoints
            return {'items':checkpoints(self.server.workbench)}
        if action == 'restore-checkpoint':
            from journey_navigator.migrations import checkpoints
            selected=next((row['backup'] for row in checkpoints(self.server.workbench) if row['version']==body['version']),None)
            if not selected:
                raise ValueError('Choose a saved Journey recovery checkpoint.')
            self.server.restore_checkpoint=selected
            self.server.request_close()
            return {'restarting':True}
        if action == 'attach':
            self.server.clients.add(str(body['client'])[:100])
            return {'attached':True}
        if action == 'detach':
            self.server.detached(str(body['client'])[:100])
            return {'detached':True}
        if action == 'destinations':
            return {'items':patrol.list()}
        if action == 'destination-create':
            return patrol.create(job,body['objective'],body['why'],body['success'],body.get('max_files',20000),body.get('max_seconds',300))
        if action == 'patrol-status':
            return patrol.status(destination)
        if action == 'patrol-begin':
            return patrol.begin(destination,refresh=body.get('refresh',False))
        if action == 'patrol-pause':
            return patrol.pause(destination)
        if action == 'patrol-answer':
            return patrol.answer(destination,body['assets'],body.get('label',''),body.get('purpose',''),body.get('decision','confirm'))
        if action == 'destination-outcome':
            return patrol.accept_outcome(destination,body['binding'],body.get('notes',''))
        if action == 'destination-images':
            return patrol.images(destination,offset,body.get('collection',''),body.get('assets'))
        if action == 'batch-suggestions':
            return patrol.suggested_batch(destination,body['assets'])
        if action == 'batch-prepare':
            return patrol.guided.prepare(patrol.row(destination)['job'],body['operations'])
        if action == 'batch-view':
            row=patrol.guided.row(body['batch'])
            if row['job'] != patrol.row(destination)['job']:
                raise PermissionError('This batch belongs to another Destination.')
            return patrol.guided.view(body['batch'])
        if action == 'batch-authorize':
            return patrol.authorize(destination,body['batch'])
        if action == 'batch-undo':
            return patrol.guided.prepare_undo(patrol.row(destination)['job'],body['receipt'])
        if type(offset) is not int or not 0 <= offset <= 1_000_000:
            raise ValueError("Choose a valid results page.")
        if action == "drives":
            return {"items": local_drives()}
        if action == "browse":
            return app.browse(body["path"], offset)
        if action == "select":
            if job is None:
                retain = body.get("retain", False)
                if type(retain) is not bool:
                    raise ValueError("Choose whether to keep a local checkpoint.")
                app = self.server.workbench if retain else self.server.temporary
            return app.select(body.get("path"), job_id=job, link_id=body.get("link"), proposals=body.get("proposals", False))
        if action == "approve":
            ticket = body["ticket"]
            return self.server.review_store(ticket).approve(ticket, proposals=body.get("proposals"))
        if action == "jobs":
            return {"items": self.server.workbench.jobs()}
        if action == "summary":
            return app.summary(job)
        if action == "step":
            return app.step(job)
        if action == "pause":
            app.pause()
            return app.summary(job)
        if action == "refresh":
            return app.refresh(job)
        if action in ("links", "issues", "groups"):
            return {"links": app.links, "issues": app.issues, "groups": app.groups}[action](job, offset)
        if action == "images":
            return app.images(job, offset, body.get("series", ""), body.get("query", ""))
        if action == "review":
            return app.review(job, body["asset"], body["decision"], body.get("label", ""), body.get("purpose", ""))
        if action == "permissions":
            return app.permissions(job)
        if action == "proposals":
            return app.permit_proposals(job, body["scope"], body["allowed"])
        if action == "revoke":
            return app.revoke(job, body["scope"], body["permission"])
        if action == "rule":
            return app.rule(job, body["project"], body["filename"], body["folder"])
        if action == "export":
            return app.export(job)
        if action == "exit":
            self.server.request_close()
            return {"closed": True}
        raise ValueError("This inspection action is unavailable.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    data = args.data_dir or local / "Journey" / "Navigator Inspection"
    hold_store = Path(r"C:\mini_ark\private\media_recovery\inventory-v2.sqlite") if os.name == "nt" else None
    perception_store = Path(r"C:\mini_ark\ark.sqlite") if os.name == "nt" else None
    owner = None
    app = None
    try:
        data = _prepare_data_dir(data.absolute())
        owner = SessionOwner(data)
        previous = owner.enter()
        if previous:
            if args.no_browser:
                print(previous,flush=True)
            else:
                webbrowser.open(previous)
            owner.close()
            return
        app = Workbench(data.absolute(), blocked=(APP, APP.parent / "ocr"), hold_store=hold_store,
                        perception_store=perception_store, ocr=find_local_ocr())
    except (OSError, ValueError) as error:
        if owner:
            owner.close()
        if os.name != "nt" or args.no_browser:
            raise
        import ctypes

        message = str(error)
        if 'already open' in message:
            message = 'An earlier Navigator holds this checkpoint and cannot accept an authenticated upgrade. Open its window, choose Manage → Close Navigator, then open this version.'
        ctypes.windll.user32.MessageBoxW(None, message, "Journey Navigator", 0x10)
        return
    try:
        with Navigator(app,owner=owner) as server:
            owner.publish(server)
            if args.no_browser:
                print(server.url, flush=True)
            else:
                webbrowser.open(server.url)
            server.serve_forever()
    finally:
        app.close()
        restore = server.restore_checkpoint if 'server' in locals() else None
        if restore:
            from journey_navigator.migrations import restore_inspection
            restore_inspection(data,restore)
        owner.close()
        if restore:
            subprocess.Popen([sys.executable,'-B','-m','journey_navigator',*sys.argv[1:]],cwd=APP)


if __name__ == "__main__":
    main()
