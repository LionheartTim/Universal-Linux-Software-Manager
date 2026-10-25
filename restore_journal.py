"""Crash-tolerant bookkeeping of restore operations (no automatic resumption).

Only package filenames and status strings are persisted, not installer output.
JSON files are private to the current user; never execute data from a journal.
"""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def state_path(home):
    return Path(home) / '.local/state/universal-linux-software-manager/restore-state.json'


def _write(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        raise OSError('Unsafe journal path')
    fd, temp = tempfile.mkstemp(prefix='.restore-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as dest:
            json.dump(payload, dest, indent=2, ensure_ascii=False)
            dest.flush()
            os.fsync(dest.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_unfinished(home):
    path = state_path(home)
    if not path.exists() and not path.is_symlink():
        return None
    if path.is_symlink() or path.parent.is_symlink():
        return {'state':'running', 'items':[], 'archive':'?', 'warning':'Unsafe restore journal path.'}
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
        if state.get('state') != 'running':
            return None
        if not isinstance(state.get('items'), list):
            return None
        return state
    except (OSError, UnicodeError, ValueError):
        return {'state':'running', 'items':[], 'archive':'?', 'warning':'Restore status file unreadable.'}


def start(home, archive, items):
    path = state_path(home)
    if path.is_symlink() or path.parent.is_symlink():
        raise OSError('Unsafe restore journal path')
    previous = read_unfinished(home)
    if previous:
        archive_old = path.parent / ('interrupted-' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f') + '.json')
        os.replace(path, archive_old)
    payload = {'schema':1, 'state':'running', 'started_utc':_utc(),
               'archive':str(archive), 'items':[{'name':str(name), 'status':'Waiting for approval'} for name in items]}
    _write(path, payload)
    return payload


def update(home, payload, index, status):
    payload['items'][index]['status'] = str(status)[:120]
    payload['updated_utc'] = _utc()
    _write(state_path(home), payload)


def finish(home, payload):
    payload['state'] = 'completed'
    payload['completed_utc'] = _utc()
    _write(state_path(home), payload)
    # Keep a bounded final record separately for troubleshooting, not secrets.
    return state_path(home)
