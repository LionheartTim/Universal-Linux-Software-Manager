"""Conservative, cross-distro backup-app selection.

There is *no* universal OS-vs-user-installed bit on Linux. Use only
high-confidence native package evidence; preserve an explicit, reversible
per-user exclusion list for everything else. This never removes software.
"""
import json
import os
import tempfile
from pathlib import Path
from feature_tools import package_id_ok

PROFILE_FORMAT = 'ulsm-backup-excluded-apps'


def identity(entry):
    return '|'.join(str(entry.get(k, '')) for k in ('kind', 'scope', 'id'))


def read_exclusions(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        if data.get('format') != PROFILE_FORMAT or not isinstance(data.get('excluded'), list):
            return set()
        return {v for v in data['excluded'] if isinstance(v, str) and 2 < len(v) <= 400 and '|' in v}
    except (OSError, ValueError, TypeError):
        return set()


def write_exclusions(path, entries):
    """Atomic, non-world-readable local preferences. No package mutations."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.ulsm-excludes-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump({'format': PROFILE_FORMAT, 'excluded': sorted(set(entries))}, out, indent=2)
            out.flush(); os.fsync(out.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def native_classifications(run):
    """Return only safely known automatic/basic packages; fail open if query fails.

    apt-mark manual is NOT sufficient for distinguishing default packages;
    apt-mark auto *is* evidence of a dependency. APT priority required or
    essential packages are core OS packages. pacman -Qd marks dependencies.
    """
    out = {}
    ok, text, _ = run(['apt-mark', 'showauto'], 25)
    if ok:
        out['DEB:auto'] = {x.strip() for x in text.splitlines() if package_id_ok(x.strip())}
    ok, text, _ = run(['dpkg-query', '-W', '-f=${binary:Package}\t${Priority}\t${Essential}\n'], 35)
    if ok:
        core = set()
        for line in text.splitlines():
            parts = line.split('\t')
            if len(parts) >= 3 and package_id_ok(parts[0]) and (parts[1] == 'required' or parts[2].lower() == 'yes'):
                core.add(parts[0])
        out['DEB:core'] = core
    ok, text, _ = run(['pacman', '-Qdq'], 25)
    if ok:
        out['Arch:auto'] = {x.strip() for x in text.splitlines() if package_id_ok(x.strip())}
    ok, text, _ = run(['pacman', '-Qqg', 'base'], 25)
    if ok:
        out['Arch:core'] = {x.strip() for x in text.splitlines() if package_id_ok(x.strip())}
    return out


def classify(entry, evidence=None, exclusions=()):
    """One of user-choice, system-default, dependency, or review.

    'review' means distro-provided vs manually installed cannot be proven.
    """
    key = identity(entry)
    if key in exclusions:
        return 'system-default'
    kind = str(entry.get('kind', ''))
    pid = str(entry.get('id', ''))
    ev = evidence or {}
    if kind == 'RPM' and entry.get('user_layered') is True:
        return 'user-choice'
    if kind in ('DEB', 'Arch'):
        base = pid.split(':', 1)[0]
        if pid in ev.get(kind+':core', ()) or base in ev.get(kind+':core', ()):
            return 'system-default'
        if pid in ev.get(kind+':auto', ()) or base in ev.get(kind+':auto', ()):
            return 'dependency'
    if kind in ('RPM', 'DEB', 'Arch', 'Snap', 'APK', 'XBPS', 'Portage', 'Nix'):
        # A native package may be in the default install even when marked manual.
        return 'review'
    return 'user-choice'


def partition_apps(entries, evidence=None, exclusions=()):
    """Default-visible / hidden rows, preserving input order and all entries."""
    shown, hidden = [], []
    for entry in entries:
        group = classify(entry, evidence, exclusions)
        enriched = dict(entry, backup_class=group)
        (hidden if group in ('system-default', 'dependency') else shown).append(enriched)
    return shown, hidden
