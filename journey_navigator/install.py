"""User-level Windows installation with staged files and a stable candidate shortcut."""

import base64
import ctypes
from hashlib import file_digest
import json
import os
from pathlib import Path
import shutil
import subprocess
from time import monotonic,sleep
from uuid import uuid4

from core.file_paths import safe_metadata
from journey_navigator.session import SessionOwner,build_info,protect
from journey_navigator.workbench import _prepare_data_dir


def verify(package):
    manifest=json.loads((package/'MANIFEST.json').read_text(encoding='utf-8'))
    for name,digest in manifest.items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('The package manifest contains an invalid path.')
        path=package/relative
        safe_metadata(path)
        with path.open('rb') as source:
            if file_digest(source,'sha256').hexdigest()!=digest:
                raise ValueError('A packaged file is missing or changed. Extract a complete candidate and run Setup again.')
    return manifest


def known_folder(identifier):
    result=ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None,identifier,None,0,result)!=0:
        raise OSError('Windows could not locate the current account application shortcuts.')
    return Path(result.value)


def shortcuts(executable):
    entries=[known_folder(2)/'Journey Navigator Candidate'/'Journey Navigator.lnk',
             known_folder(16)/'Journey Navigator Candidate.lnk']
    payload={'target':str(executable),'working':str(executable.parent),'links':[str(path) for path in entries]}
    data=base64.b64encode(json.dumps(payload).encode()).decode()
    script='''$ErrorActionPreference='Stop'
$data=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('''+"'"+data+"'"+''')) | ConvertFrom-Json
$shell=New-Object -ComObject WScript.Shell
foreach($path in $data.links) {
 [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path)) | Out-Null
 if(Test-Path -LiteralPath $path) {
  $prior=$shell.CreateShortcut($path)
  if($prior.TargetPath -and -not $prior.TargetPath.StartsWith([IO.Path]::GetDirectoryName([IO.Path]::GetDirectoryName($data.target)),[StringComparison]::OrdinalIgnoreCase)) {
   throw 'An unrelated shortcut already uses the candidate name. Rename that shortcut, then run Setup again.'
  }
 }
 $link=$shell.CreateShortcut($path)
 $link.TargetPath=$data.target
 $link.WorkingDirectory=$data.working
 $link.Description='Journey Navigator Candidate · foreground Guided Patrol'
 $link.Save()
}
'''
    encoded=base64.b64encode(script.encode('utf-16-le')).decode()
    subprocess.run([str(Path(os.environ['SystemRoot'])/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'),
                    '-NoProfile','-NonInteractive','-EncodedCommand',encoded],check=True,capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)


def main():
    owner=None
    try:
        if os.name!='nt':
            raise ValueError('Use Setup from the Windows candidate package.')
        package=Path(__file__).resolve().parents[2]
        if not (package/'BUILD.txt').is_file():
            raise ValueError('Extract the complete Windows candidate and open Setup Journey.exe.')
        info=build_info()
        local=Path(os.environ['LOCALAPPDATA'])
        home=local/'Programs'/'Journey Navigator Candidate'
        _prepare_data_dir(home)
        if ctypes.windll.user32.MessageBoxW(None,
            f"Install {info['version']} ({info['commit']}) for your current Windows account?\n\n"
            f"Application files: {home}\n\nSaved work stays in Journey's separate local data folder. Setup creates a desktop and Start menu shortcut.",
            'Journey Setup',0x24)!=6:
            return
        approved_files=verify(package)
        data=_prepare_data_dir(local/'Journey'/'Navigator Inspection')
        owner=SessionOwner(data,info=info)
        owner.enter()
        final=home/('build-'+info['build'])
        if final.exists():
            verify(final)
        else:
            staging=home/('staging-'+uuid4().hex)
            try:
                staging.mkdir()
                for name in (*approved_files,'MANIFEST.json'):
                    target=staging/name
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(package/name,target)
                verify(staging)
                staging.rename(final)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        shortcuts(final/'Journey Navigator.exe')
        owner.close();owner=None
        subprocess.Popen([str(final/'Journey Navigator.exe')],cwd=final)
        deadline=monotonic()+30
        while monotonic()<deadline:
            try:
                record=json.loads(protect((data/'navigator-session.dat').read_bytes(),decrypt=True))
                probe=SessionOwner(data,info=info)
                probe._request(record,'status')
                if record['build']==info['build']:
                    return
            except (OSError,ValueError,KeyError):
                pass
            sleep(.1)
        raise ValueError('The files installed, but Navigator has not reported ready. Open the Journey Navigator Candidate desktop shortcut once the previous window has closed.')
    except (OSError,ValueError,subprocess.SubprocessError) as error:
        ctypes.windll.user32.MessageBoxW(None,str(error),'Journey Setup',0x10)
    finally:
        if owner:
            owner.close()


if __name__=='__main__':main()
