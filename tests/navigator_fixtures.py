"""Disposable filesystem relationships for Navigator acceptance tests."""

import os
from pathlib import Path
import subprocess


def make_link(path, target, kind="shortcut"):
    if os.name == "nt" and kind == "shortcut":
        env = os.environ | {"JOURNEY_FIXTURE_LINK": str(path), "JOURNEY_FIXTURE_TARGET": str(target)}
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                        "$ErrorActionPreference = 'Stop'; "
                        "$link = (New-Object -ComObject WScript.Shell).CreateShortcut($env:JOURNEY_FIXTURE_LINK); "
                        "$link.TargetPath = $env:JOURNEY_FIXTURE_TARGET; $link.Save()"],
                       env=env, check=True, capture_output=True)
    elif os.name == "nt" and kind == "junction":
        subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(path), str(target)],
                       check=True, capture_output=True)
    else:
        path.symlink_to(target, target_is_directory=True)
    return Path(path)
