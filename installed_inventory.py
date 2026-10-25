"""Read the REAL installed software inventory; discovery is never the source of truth.

A query failure is recorded, not represented as "up to date". All mutating
commands remain in the existing GUI and require explicit approval.
"""
import json
from pathlib import Path
from feature_tools import record, package_id_ok, scan_updates
from portable_managers import installed_extra


def flatpak_scope(installation):
    name = str(installation).strip()
    if name.lower() == 'user': return 'user'
    if name.lower() in ('system', 'default'): return 'system'
    return name if package_id_ok(name) else None


def installed_software(run, manager, app_dir, tracking=None):
    """Read installed packages from the host and ~/Applications, without modifying them."""
    rows, notes = [], []

    def query(kind, argv, limit=60):
        ok, out, err = run(argv, limit)
        if not ok: notes.append(f'{kind}: installed software could not be read: {str(err)[-130:]}')
        return out if ok else None

    text = query('Flatpak', ['flatpak', 'list', '--app',
                            '--columns=name,application,version,installation'])
    if text is not None:
        for line in text.splitlines():
            parts = [p.strip() for p in line.split('\t')]
            if len(parts) != 4 or not package_id_ok(parts[1]): continue
            scope = flatpak_scope(parts[3])
            if scope:
                rows.append(record('Flatpak', parts[0], parts[1], parts[2], scope, parts[3]))
            else: notes.append('Flatpak: skipped an installation with an invalid installation identifier.')

    if app_dir.is_dir():
        for path in sorted(app_dir.iterdir()):
            if path.is_symlink() or not path.is_file() or not path.name.lower().endswith('.appimage'):
                continue
            entry = record('AppImage', path.stem, path.name, scope='USER')
            entry['update_source'] = 'unknown'
            rows.append(entry)
    tracking = tracking or {}
    for repo, item in tracking.items():
        filename = item.get('file', '') if isinstance(item, dict) else ''
        for row in rows:
            if row['kind'] == 'AppImage' and row['id'] == filename:
                row['update_source'] = 'GitHub'
                row['github_repo'] = repo
                row['version'] = str(item.get('tag', ''))[:140]

    rpm_manager = manager('RPM')
    if rpm_manager == 'rpm-ostree':
        text = query('RPM', ['rpm-ostree', 'status', '--json'], 40)
        if text is not None:
            try:
                deployments = json.loads(text).get('deployments', [])
                active = next((d for d in deployments if d.get('booted')), None)
                if active is None: raise ValueError('No booted deployment')
                pending = next((d for d in deployments if d.get('staged') or d.get('pending')), None)
                if pending is None and deployments and not deployments[0].get('booted'):
                    pending = deployments[0]
                def layers(dep):
                    names = set()
                    for key in ('requested-packages', 'requested-local-packages',
                                'requested-local-fileoverride-packages'):
                        for item in dep.get(key, []) or []:
                            if isinstance(item, str):
                                name = item.rsplit('/', 1)[-1] if 'local' in key else item
                                if name.endswith('.rpm'):
                                    name = name.removesuffix('.rpm').split('-', 1)[0]
                                if package_id_ok(name): names.add(name)
                    return names
                active_names = layers(active)
                pending_names = layers(pending) if pending else active_names
                for pid in sorted(active_names | pending_names):
                    e = record('RPM', pid, pid, scope='SYSTEM')
                    if pending and ((pid in active_names) != (pid in pending_names)):
                        e['pending'] = True
                    rows.append(e)
            except (ValueError, TypeError, AttributeError) as exc:
                notes.append('RPM: invalid rpm-ostree status: ' + str(exc)[:130])
    elif rpm_manager in ('dnf', 'dnf5', 'zypper'):
        text = query('RPM', ['rpm', '-qa', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}\n'])
        if text is not None:
            for line in text.splitlines():
                parts = line.split('\t')
                if len(parts) >= 2 and package_id_ok(parts[0]):
                    rows.append(record('RPM', parts[0], parts[0], parts[1], 'SYSTEM'))

    if manager('DEB') == 'apt-get':
        text = query('DEB', ['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\n'])
        if text is not None:
            for line in text.splitlines():
                parts = line.split('\t')
                if len(parts) >= 2 and package_id_ok(parts[0]):
                    rows.append(record('DEB', parts[0], parts[0], parts[1], 'SYSTEM'))

    if manager('Arch') == 'pacman':
        text = query('Arch', ['pacman', '-Q'])
        if text is not None:
            for line in text.splitlines():
                parts = line.split()
                if len(parts) >= 2 and package_id_ok(parts[0]):
                    rows.append(record('Arch', parts[0], parts[0], parts[1], 'SYSTEM'))

    if manager('Snap') == 'snap':
        text = query('Snap', ['snap', 'list'])
        if text is not None:
            for line in text.splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2 and package_id_ok(parts[0]):
                    rows.append(record('Snap', parts[0], parts[0], parts[1], 'SYSTEM'))

    extra_rows, extra_notes = installed_extra(run, manager)
    rows.extend(extra_rows)
    notes.extend(extra_notes)
    return rows, notes


def merge_updates(installed, updates, checked=()):
    """Map update candidates onto actual installed packages (never string-guess names)."""
    checked = set(checked)
    by_exact = {}
    github_by_repo = {}
    for candidate in updates:
        if candidate.get('kind') == 'GitHub':
            github_by_repo[candidate.get('id')] = candidate
        else:
            scope = candidate.get('scope', '')
            if candidate.get('kind') == 'Flatpak': scope = flatpak_scope(scope)
            else: scope = ''
            by_exact[(candidate.get('kind'), candidate.get('id'), scope)] = candidate
    # apt may omit architecture on its upgradable list while dpkg-query uses
    # package:arch. Infer only when exactly one installed identity matches.
    deb_by_base = {}
    for item in installed:
        if item.get('kind') == 'DEB':
            deb_by_base.setdefault(item['id'].split(':', 1)[0], []).append(item['id'])
    combined = []
    for row in installed:
        entry = dict(row)
        kind = entry['kind']
        entry['installed_version'] = entry.get('version', '')
        entry['available_version'] = ''
        entry['status'] = 'not_checked'
        found = None
        if kind == 'AppImage':
            repo = entry.get('github_repo')
            if repo:
                found = github_by_repo.get(repo)
                entry['status'] = 'no_update' if ('GitHub', repo) in checked else 'not_checked'
            else: entry['status'] = 'unknown_source'
        else:
            scope = flatpak_scope(entry.get('scope', '')) if kind == 'Flatpak' else ''
            found = by_exact.get((kind, entry['id'], scope))
            if (kind == 'DEB' and not found and ':' in entry['id'] and
                    len(deb_by_base.get(entry['id'].split(':', 1)[0], [])) == 1):
                found = by_exact.get((kind, entry['id'].split(':', 1)[0], ''))
            checkkey = (kind, scope if kind == 'Flatpak' else '')
            entry['status'] = 'no_update' if checkkey in checked else 'not_checked'
            if kind == 'RPM' and entry.get('pending'): entry['status'] = 'reboot_required'
            if kind == 'RPM' and ('RPM', 'system_updater') in checked:
                entry['status'] = 'system_updater'
            if kind in ('Arch', 'APK', 'XBPS', 'Nix', 'Portage'): entry['status'] = 'system_updater'
        if found and entry['status'] not in ('reboot_required', 'system_updater'):
            entry['status'] = 'available'
            entry['available_version'] = found.get('version', '')
            if kind == 'AppImage':
                entry['release'] = found.get('release')
        combined.append(entry)
    return sorted(combined, key=lambda row:(row['name'].casefold(),row['kind'],row['id']))


def scan_all_installed_updates(run, manager, app_dir, tracking=None, github_lookup=None):
    """Inventory is authoritative; an update is shown only for an installed ID."""
    installed, notes = installed_software(run, manager, app_dir, tracking=tracking)
    checked = set()
    scopes = sorted({row['scope'] for row in installed if row['kind'] == 'Flatpak'})
    updates, update_notes = scan_updates(run, manager,
                                         github_lookup=(lambda: github_lookup(checked)) if github_lookup else None,
                                         checked=checked, flatpak_scopes=scopes)
    combined = merge_updates(installed, updates, checked)
    return combined, notes + update_notes
