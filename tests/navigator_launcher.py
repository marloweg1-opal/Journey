"""Launch the real Windows EXE and verify authenticated single-instance ownership."""

import argparse
import ctypes
from ctypes import wintypes
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import shutil
from tempfile import TemporaryDirectory
from time import monotonic,sleep
from urllib.request import Request,urlopen

from journey_navigator.session import protect,process_identity
from journey_navigator.install import known_folder,verify
from journey_navigator.links import shortcut_path


def choose_fixture_dialog(title,runtime,button=6):
    """Automate only this fixture's install/update dialogs, never account approval."""
    assert title in ('Journey Setup','Journey update')
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR]
    user.FindWindowW.restype=wintypes.HWND
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.GetDlgItem.argtypes=[wintypes.HWND,ctypes.c_int]
    user.GetDlgItem.restype=wintypes.HWND
    user.IsWindowVisible.argtypes=[wintypes.HWND]
    user.IsWindowEnabled.argtypes=[wintypes.HWND]
    user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    deadline=monotonic()+30
    while monotonic()<deadline:
        window=user.FindWindowW('#32770',title)
        if window:
            pid=wintypes.DWORD()
            user.GetWindowThreadProcessId(window,ctypes.byref(pid))
            if Path(process_identity(pid.value)['executable'])==runtime.resolve():
                control=user.GetDlgItem(window,button)
                # Windows exposes the dialog before its children are ready.
                # Wait for the exact fixture-owned decision, not just its title.
                if control and user.IsWindowVisible(control) and user.IsWindowEnabled(control):
                    assert user.PostMessageW(window,0x0111,button,0)
                    return
        sleep(.1)
    raise AssertionError(f'The isolated fixture did not open its expected {title} dialog.')


def manifest(path):
    deadline=monotonic()+30
    while monotonic()<deadline:
        try:
            record=json.loads(protect(path.read_bytes(),decrypt=True))
            origin=f"http://127.0.0.1:{record['port']}"
            request=Request(origin+'/api/session/status',data=b'{}',headers={'Content-Type':'application/json','Origin':origin,'X-Journey-Control':record['control']})
            with urlopen(request,timeout=1) as response:
                result=json.load(response)
            if result['session']==record['session']:
                return record
        except (OSError,ValueError):
            sleep(.1)
    raise AssertionError('The normal launcher did not publish a verified running session.')


def stop(record):
    origin=f"http://127.0.0.1:{record['port']}"
    request=Request(origin+'/api/session/shutdown',data=b'{}',headers={'Content-Type':'application/json','Origin':origin,'X-Journey-Control':record['control']})
    with urlopen(request,timeout=5) as response:
        assert json.load(response)['session']==record['session']


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--application',required=True,type=Path)
    args=parser.parse_args()
    with TemporaryDirectory(prefix='journey-normal-launch-',ignore_cleanup_errors=True) as temp:
        root=Path(temp).resolve()
        env=os.environ | {'LOCALAPPDATA':str(root)}
        path=root/'Journey'/'Navigator Inspection'/'navigator-session.dat'
        links=[known_folder(2)/'Journey Navigator Candidate'/'Journey Navigator.lnk',
               known_folder(16)/'Journey Navigator Candidate.lnk']
        assert not any(link.exists() for link in links),'Do not overwrite an existing candidate installation during a fixture.'
        first=subprocess.Popen([str(args.application.resolve())],env=env)
        record=None
        try:
            record=manifest(path)
            second=subprocess.run([str(args.application.resolve())],env=env,timeout=30)
            assert second.returncode==0
            assert manifest(path)['session']==record['session']
            assert first.poll() is None
            stop(record);first.wait(timeout=30)
            assert first.returncode==0
            third=subprocess.Popen([str(args.application.resolve())],env=env)
            next_record=manifest(path)
            assert next_record['session']!=record['session']
            # A declared previous-build fixture exercises the actual handoff dialog.
            previous=root/'Previous candidate'
            shutil.copytree(args.application.resolve().parent,previous)
            metadata=previous/'BUILD.txt'
            metadata.write_text(metadata.read_text(encoding='utf-8').replace(next_record['commit'],'fixture-previous-build'),encoding='utf-8')
            hashes=json.loads((previous/'MANIFEST.json').read_text(encoding='utf-8'))
            hashes['BUILD.txt']=sha256(metadata.read_bytes()).hexdigest()
            (previous/'MANIFEST.json').write_text(json.dumps(hashes),encoding='utf-8')
            earlier=subprocess.Popen([str(previous/'Journey Navigator.exe')],env=env)
            choose_fixture_dialog('Journey update',previous/'runtime'/'pythonw.exe')
            third.wait(timeout=30)
            previous_record=manifest(path)
            assert previous_record['commit']=='fixture-previous-build'
            assert previous_record['session']!=next_record['session']
            # Run the real Setup EXE. Only installation consent is automated here.
            setup=subprocess.Popen([str(args.application.resolve().parent/'Setup Journey.exe')],env=env)
            runtime=args.application.resolve().parent/'runtime'/'pythonw.exe'
            choose_fixture_dialog('Journey Setup',runtime)
            choose_fixture_dialog('Journey update',runtime)
            earlier.wait(timeout=30);setup.wait(timeout=45)
            assert earlier.returncode==0 and setup.returncode==0
            installed=manifest(path)
            assert installed['commit']==next_record['commit']
            installation=Path(installed['location'])
            assert installation.is_relative_to(root/'Programs'/'Journey Navigator Candidate')
            verify(installation)
            for link in links:
                assert Path(shortcut_path(link.read_bytes()))==installation/'Journey Navigator.exe'
            stop(installed)
            deadline=monotonic()+30
            while path.exists() and monotonic()<deadline:sleep(.1)
            assert not path.exists(),'The installed service did not release ownership.'
            shutil.rmtree(root/'Journey')
            print('Normal EXE launch, compatible instance reopening, authenticated shutdown, lock release and clean relaunch passed.')
            print('Actual changed-build handoff, Setup EXE, manifest-verified staged installation and stable shortcuts passed using automated installation consent only.')
        finally:
            if path.exists():
                try:stop(manifest(path))
                except (OSError,ValueError,AssertionError):pass
            if first.poll() is None and record is not None:first.wait(timeout=30)
            for link in links:
                if link.exists() and Path(shortcut_path(link.read_bytes())).is_relative_to(root/'Programs'):
                    link.unlink()
            if links[0].parent.exists() and not any(links[0].parent.iterdir()):links[0].parent.rmdir()


if __name__=='__main__':main()
