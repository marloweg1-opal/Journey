"""Authenticated single-instance handoff and visible build identity."""

from contextlib import ExitStack
import ctypes
from ctypes import wintypes
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sys
from time import monotonic, sleep
from urllib.request import Request, urlopen
from uuid import uuid4

from core.file_paths import safe_metadata
from core.process_lock import ProcessBusyError, process_lock


VERSION = "0.6 Project Stewardship"
APP_ID = "Journey.Navigator"


def protect(data, *, decrypt=False):
    if os.name != "nt":
        return data
    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]
    memory = ctypes.create_string_buffer(data)
    original = Blob(len(data), ctypes.cast(memory, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    library = ctypes.WinDLL("crypt32", use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    if not function(ctypes.byref(original), None, None, None, None, 1, ctypes.byref(output)):
        raise PermissionError("Windows could not access this account's Journey session record.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree(output.data)


def process_identity(pid):
    if os.name != "nt":
        return {"pid": pid, "created": Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[19],
                "executable": str(Path(f"/proc/{pid}/exe").resolve(strict=True))}
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise ProcessLookupError("The previous Navigator process is unavailable.")
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        path, count = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)) or not kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(count)):
            raise PermissionError("Windows could not verify the previous Navigator process.")
        return {"pid": pid, "created": (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime,
                "executable": str(Path(path.value).resolve())}
    finally:
        kernel.CloseHandle(handle)


def build_info():
    root = Path(__file__).resolve().parents[1]
    metadata = root.parent / "BUILD.txt"
    commit = "source"
    if metadata.is_file():
        commit = metadata.read_text(encoding="utf-8").splitlines()[0].removeprefix("Journey source commit ")
    digest = sha256()
    digest.update(commit.encode())
    for folder in (root / "journey_navigator", root / "core"):
        for file in sorted(item for item in folder.iterdir() if item.suffix in ('.py','.html','.js','.css')):
            digest.update(file.name.encode())
            digest.update(file.read_bytes())
    for file in (root/'index.html',root/'examples'/'carebloom'/'project_tokens.json',root.parent/'approval.sha256'):
        if file.is_file():
            digest.update(file.read_bytes())
    return {"application": APP_ID, "version": VERSION, "commit": commit, "build": digest.hexdigest()[:16],
            "location": str(root.parent if metadata.is_file() else root), "executable": str(Path(sys.executable).resolve()),
            "installation": "Isolated candidate", "session": uuid4().hex}


def confirm_handoff(previous, current):
    if os.name != "nt":
        return False
    return ctypes.windll.user32.MessageBoxW(None,
        f"The running Navigator is {previous['version']} ({previous['build']}).\n\n"
        f"You opened {current['version']} ({current['build']}).\n\n"
        "Close the previous Navigator at a safe checkpoint and continue with this version?",
        "Journey update", 0x24) == 6


class SessionOwner:
    def __init__(self, data, *, info=None):
        self.data = Path(data)
        self.info = info or build_info()
        self.path = self.data / "navigator-session.dat"
        self.lock = self.data / "navigator-session.lock"
        self.control = secrets.token_urlsafe(32)
        self.resources = ExitStack()
        self.owns = False
        self.reopened = None

    def _acquire(self):
        self.resources.enter_context(process_lock(self.lock))
        self.owns = True

    def _request(self, record, action):
        if record.get("application") != APP_ID or process_identity(record["process"]["pid"]) != record["process"]:
            raise ValueError("The saved service identity does not match a live Navigator.")
        origin = f"http://127.0.0.1:{int(record['port'])}"
        request = Request(origin + "/api/session/" + action, data=b"{}", headers={
            "Content-Type": "application/json", "Origin": origin, "X-Journey-Control": record["control"]})
        with urlopen(request, timeout=3) as response:
            result = json.load(response)
        if result.get("session") != record["session"]:
            raise ValueError("The responding service has a different session identity.")
        return result

    def enter(self):
        try:
            self._acquire()
            return None
        except ProcessBusyError:
            pass
        try:
            safe_metadata(self.path)
            record = json.loads(protect(self.path.read_bytes(), decrypt=True))
            self._request(record, "status")
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("The previous Navigator cannot accept a verified handoff. Open its window, choose Manage → Close Navigator, then open this version again.") from None
        self.reopened = record
        if record["build"] == self.info["build"]:
            return self._request(record, "activate")["url"]
        if not confirm_handoff(record, self.info):
            return self._request(record, "activate")["url"]
        self._request(record, "shutdown")
        deadline = monotonic() + 30
        while monotonic() < deadline:
            try:
                self._acquire()
                return None
            except ProcessBusyError:
                sleep(.1)
        raise ValueError("The previous Navigator is still finishing a safe checkpoint. Wait for its window to report closed, then open this version again.")

    def publish(self, server):
        record = self.info | {"control": self.control, "port": server.server_port, "process": process_identity(os.getpid())}
        temporary = self.path.with_suffix(".new")
        with temporary.open("wb") as output:
            output.write(protect(json.dumps(record).encode()))
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)

    def close(self):
        if self.owns:
            self.path.unlink(missing_ok=True)
        self.resources.close()
