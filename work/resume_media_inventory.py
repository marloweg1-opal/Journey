"""Bounded continuation using a private ledger; never repairs or retries holds."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from core.media_inventory import register, batch, hash_batch
from core.process_lock import process_lock, ProcessBusyError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--roots',nargs='*',default=[])
    parser.add_argument('--max-directories',type=int,default=100)
    parser.add_argument('--max-seconds',type=float,default=15)
    parser.add_argument('--hash-files',type=int,default=0)
    args = parser.parse_args()
    folder = ROOT/'private'/'media_recovery'
    folder.mkdir(parents=True,exist_ok=True)
    try:
        with process_lock(folder/'inventory.lock'):
            result = continue_inventory(folder, args)
    except ProcessBusyError as exc:
        print(json.dumps({'state':'ALREADY_RUNNING','error':str(exc),'managed_mutations':0}))
        return 2
    print(json.dumps({k:v for k,v in result.items() if k!='held'},indent=2))
    return 0


def continue_inventory(folder, args):
    with closing(sqlite3.connect(folder/'inventory-v2.sqlite')) as conn:
        with conn:
            register(conn,args.roots)
            result = batch(conn,max_directories=args.max_directories,max_seconds=args.max_seconds)
            if args.hash_files:
                result.update(hash_batch(conn,max_files=args.hash_files,max_seconds=args.max_seconds))
    # Keep the earlier hash/validation evidence; attach inventory progress rather
    # than misrepresenting newly discovered files as already validated.
    destination = folder/'latest_summary.json'
    document = json.loads(destination.read_text(encoding='utf-8')) if destination.exists() else {}
    document['resumable_inventory'] = result
    temporary = folder/'inventory-summary.tmp'
    temporary.write_text(json.dumps(document,indent=2),encoding='utf-8')
    os.replace(temporary,destination)
    return result


if __name__ == '__main__':
    sys.exit(main())
