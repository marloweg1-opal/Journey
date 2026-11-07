"""Account verification uses a native credential prompt, with no API approval flag."""

from dataclasses import dataclass
from hashlib import file_digest
import os
from pathlib import Path
import subprocess
import time


@dataclass(frozen=True)
class Consent:
    binding: str
    account: str
    verified_at: float
    method: str


class WindowsApprover:
    def __init__(self):
        self.active = None

    def cancel(self):
        if self.active is not None and self.active.poll() is None:
            self.active.terminate()

    def verify(self, binding, description):
        if os.name != "nt":
            raise PermissionError("Guided execution requires this candidate's Windows account verification.")
        root = Path(__file__).resolve().parents[2]
        helper = root / "Journey Approval.exe"
        digest_path = root / "approval.sha256"
        try:
            with helper.open("rb") as stream:
                actual = file_digest(stream, "sha256").hexdigest()
            expected = digest_path.read_text(encoding="ascii").strip()
            if actual != expected:
                raise ValueError()
        except (OSError, ValueError):
            raise PermissionError("The packaged Journey approval component is unavailable or changed. Reinstall the complete candidate.") from None
        process = subprocess.Popen([str(helper), binding], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
        self.active = process
        try:
            output, _ = process.communicate(description.encode("utf-8"), timeout=300)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.communicate(timeout=5)
            raise PermissionError("Account verification timed out. Review the batch again.") from None
        finally:
            self.active = None
        rows = output.decode("utf-8", errors="replace").splitlines()
        if process.returncode == 3:
            raise PermissionError("Account approval was canceled. The batch stays available for review.")
        if process.returncode or len(rows) != 2 or rows[0] != binding or not rows[1].startswith("S-1-"):
            raise PermissionError("Windows could not verify approval by the current account. Use its sign-in password and review the batch again.")
        return Consent(binding, rows[1], time.time(), "Windows credential verification")
