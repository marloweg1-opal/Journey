"""Launch the real Windows EXE and verify authenticated single-instance ownership."""

import argparse
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic,sleep
from urllib.request import Request,urlopen

from journey_navigator.session import protect


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
            stop(next_record);third.wait(timeout=30)
            assert third.returncode==0
            import shutil
            shutil.rmtree(root/'Journey')
            print('Normal EXE launch, compatible instance reopening, authenticated shutdown, lock release and clean relaunch passed.')
        finally:
            if first.poll() is None and record is not None:
                stop(record);first.wait(timeout=30)


if __name__=='__main__':main()
