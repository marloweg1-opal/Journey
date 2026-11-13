"""Build a portable x64 Studio with unmodified Inkscape, corresponding source and licenses."""
import argparse
from hashlib import file_digest
import json,os,shutil,subprocess,sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile,ZIP_DEFLATED
from build_windows_planner import EMBED,PYTHON_VERSION,ROOT,fetch,extract_tk
from build_windows_vision_lab import PILLOW_SHA

INK_URL='https://media.inkscape.org/dl/resources/file/inkscape-1.4.2_2025-05-13_f4327f4-x64.msi'
INK_SHA='cdb54ddf15fb8aba98c48072f93e5a7b9063fb30e33ccb6b1d3cb9b42ec0a508'
SOURCE_URL='https://media.inkscape.org/dl/resources/file/inkscape-1.4.2.tar.xz'
SOURCE_SHA='2000530c7917e5260c9e8575a7154ff6926643d2006487d714e304a963f0c782'


def download(cache,name,url,digest):
    path=cache/name
    if not path.exists():
        partial=path.with_suffix(path.suffix+'.partial')
        with urlopen(url,timeout=180) as source,partial.open('wb') as target:shutil.copyfileobj(source,target)
        partial.replace(path)
    with path.open('rb') as stream:actual=file_digest(stream,'sha256').hexdigest()
    if actual!=digest:raise ValueError('Dependency checksum mismatch: '+name)
    return path


def build(output,cache,wheel,zig):
    if os.name!='nt':raise ValueError('The reproducible portable Windows build runs on the Windows acceptance runner.')
    cache.mkdir(parents=True,exist_ok=True);output.mkdir(parents=True,exist_ok=True)
    with wheel.open('rb') as f:
        if file_digest(f,'sha256').hexdigest()!=PILLOW_SHA:raise ValueError('Use the pinned Pillow 12.2.0 cp314 x64 wheel.')
    ink=download(cache,'inkscape-1.4.2.msi',INK_URL,INK_SHA)
    source=download(cache,'inkscape-1.4.2.tar.xz',SOURCE_URL,SOURCE_SHA)
    with TemporaryDirectory(prefix='journey-icon-studio-build-') as temp:
        staging=Path(temp);package=staging/'Journey Icon Studio';runtime=package/'runtime';app=package/'app';runtime.mkdir(parents=True)
        with ZipFile(fetch(cache,EMBED)) as z:z.extractall(runtime)
        (runtime/'python314._pth').write_text('python314.zip\n.\nDLLs\n../app\n',encoding='ascii')
        extract_tk(fetch(cache,'tcltk.msi'),staging/'tcltk',runtime,'msiextract')
        with ZipFile(wheel) as z:z.extractall(app)
        shutil.copytree(ROOT/'journey_icon_studio',app/'journey_icon_studio',ignore=shutil.ignore_patterns('__pycache__','references'))
        unpack=staging/'inkscape-extract';unpack.mkdir()
        subprocess.run(['msiexec.exe','/a',str(ink),'/qn',f'TARGETDIR={unpack}'],check=True)
        executable=next((p for p in unpack.rglob('inkscape.exe') if p.parent.name=='bin'),None)
        if not executable:raise ValueError('The official archive did not contain the expected Inkscape binary layout.')
        shutil.copytree(executable.parent.parent,package/'inkscape')
        third=package/'Third-party source and licenses';third.mkdir();shutil.copyfile(source,third/source.name)
        (third/'READ-ME.txt').write_text('Inkscape 1.4.2 is included unmodified under GPL-2.0-or-later. Its corresponding source archive is included alongside this notice. Inkscape licenses and notices are preserved in the inkscape directory.\n\nOfficial sources:\n'+INK_URL+'\n'+SOURCE_URL+'\n\nJourney Icon Studio is a separate Python application that invokes Inkscape as a local editor and renderer. Its source and MIT license are included. Python, Tcl/Tk and Pillow retain their distribution licenses. No editor, runtime or project data are installed into Windows.\n',encoding='utf-8')
        shutil.copyfile(ROOT/'LICENSE',package/'JOURNEY-LICENSE.txt');shutil.copyfile(ROOT/'docs/ICON_STUDIO.md',package/'START-HERE.md')
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
        (package/'BUILD.txt').write_text(f'Journey Icon Studio source {commit}\nInkscape 1.4.2\nCPython {PYTHON_VERSION}\nPillow 12.2.0\n',encoding='utf-8')
        (package/'Start Icon Studio.cmd').write_text('@echo off\ncd /d "%~dp0"\nstart "Journey Icon Studio" "runtime\\pythonw.exe" -B -m journey_icon_studio\n',encoding='ascii')
        subprocess.run([*zig,'cc','-target','x86_64-windows-gnu','-municode','-Wl,--subsystem,windows','-Os','-s',
            '-DJOURNEY_MODULE=L"journey_icon_studio"','-DJOURNEY_TITLE=L"Journey Icon Studio"','tools/windows/launcher.c','-o',str(package/'Journey Icon Studio.exe')],cwd=ROOT,check=True)
        manifest={}
        for p in package.rglob('*'):
            if p.is_file():
                with p.open('rb') as stream:manifest[p.relative_to(package).as_posix()]=file_digest(stream,'sha256').hexdigest()
        (package/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
        archive=output/'Journey-Icon-Studio-Windows-x64.zip'
        with ZipFile(archive,'w',ZIP_DEFLATED,compresslevel=6) as z:
            for p in package.rglob('*'):
                if p.is_file():z.write(p,p.relative_to(staging))
    with archive.open('rb') as f:print(json.dumps({'path':str(archive),'sha256':file_digest(f,'sha256').hexdigest(),'commit':commit}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output',type=Path);parser.add_argument('--cache',type=Path,required=True);parser.add_argument('--wheel',type=Path,required=True)
    args=parser.parse_args();build(args.output.resolve(),args.cache.resolve(),args.wheel.resolve(),[sys.executable,'-m','ziglang'])
