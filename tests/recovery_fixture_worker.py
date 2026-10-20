"""Subprocess crash injector. Operates only on a test-created fixture ledger."""
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import apply, journal


def main():
    root = Path(sys.argv[1]).resolve()
    if not (root / 'DISPOSABLE_GATE_A_FIXTURE').is_file():
        raise RuntimeError('Disposable fixture marker required')
    boundary = sys.argv[2]
    native = len(sys.argv) > 3 and sys.argv[3] == 'native'
    conn = sqlite3.connect(root/'fixture.sqlite')
    conn.row_factory = sqlite3.Row
    begin, complete = journal.begin_transaction, journal.complete_operation
    original_move = apply._move_no_replace

    def crash(name):
        if boundary == name:
            os._exit(73)

    def begin_wrapped(*args, **kwargs):
        value = begin(*args, **kwargs)
        crash('intent_committed')
        return value

    def move(source, destination):
        source, destination = Path(source).resolve(), Path(destination).resolve()
        if not source.is_relative_to(root) or not destination.is_relative_to(root):
            raise RuntimeError('Fixture escaped its root')
        if native:
            original_move(source, destination)
            crash('source_removed')
            return
        data = source.read_bytes()
        with destination.open('xb') as stream:
            stream.write(data[:3])
            stream.flush()
            os.fsync(stream.fileno())
            crash('partial_copy')
            stream.write(data[3:])
            stream.flush()
            os.fsync(stream.fileno())
        crash('copy_complete')
        source.unlink()
        crash('source_removed')

    def complete_wrapped(*args, **kwargs):
        crash('before_verification_receipt')
        value = complete(*args, **kwargs)
        crash('verification_committed')
        return value

    with patch.object(journal, 'check_kill_switch'), patch.object(apply, 'check_operation_magnitude'), \
         patch.object(apply, 'move_evidence_hold', return_value=None), \
         patch.object(journal, 'begin_transaction', begin_wrapped), \
         patch.object(journal, 'complete_operation', complete_wrapped), \
         patch.object(apply, '_move_no_replace', move):
        apply.execute_apply(conn, {'to_apply':[{'item_id':1, 'action':'move'}]}, verbose=False)
    conn.close()


if __name__ == '__main__':
    main()
