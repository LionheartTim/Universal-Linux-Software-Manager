"""Read-only software discovery, package list backup and conservative command routing.

All package searches run on the host via the injected runner. They never install
anything. Mutating operations require user confirmation in the GUI.
"""
import json
import re
from datetime import datetime, timezone

KINDS = ('Flatpak', 'AppImage', 'RPM', 'DEB', 'Arch', 'Snap', 'APK', 'XBPS', 'Portage', 'Nix')
PACKAGE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+@:-]{0,199}$')


def package_id_ok(value):
    return isinstance(value, str) and bool(PACKAGE_RE.fullmatch(value)) and not value.startswith('-')


def record(kind, name, package_id, version='', scope='', detail=''):
    return dict(kind=kind, name=str(name)[:240], id=str(package_id),
                version=str(version)[:140], scope=str(scope)[:80], detail=str(detail)[:400])


def flatpak_search_rows(text):
    rows = []
    for line in text.splitlines():
        parts = line.split('\t')
        if len(parts) >= 4 and package_id_ok(parts[1].strip()):
            name, pid, version, remote = [x.strip() for x in parts[:4]]
            if remote:
                rows.append(record('Flatpak', name, pid, version, remote))
    return rows


def search_software(run, manager, query, flathub_lookup=None, github_lookup=None):
    query = query.strip()
    if not (2 <= len(query) <= 80) or any(ord(ch) < 32 for ch in query):
        return [], ['Search term must be between 2 and 80 characters.']
    found, warnings = [], []
    ok, out, err = run(['flatpak', 'search', '--columns=name,application,version,remotes', query], 50)
    if ok:
        found += flatpak_search_rows(out)
    else:
        warnings.append('Flatpak: ' + str(err)[-160:])
    native = manager('RPM') or manager('DEB') or manager('Arch')
    if native in ('dnf','dnf5'):
        ok, out, err = run([native, 'search', query], 70)
        if ok:
            for line in out.splitlines():
                m = re.match(r'^\s*([A-Za-z0-9_+.-]+)\.(?:x86_64|aarch64|noarch|i686)\s*:\s*(.+)$', line)
                if m and package_id_ok(m[1]): found.append(record('RPM',m[1],m[1],detail=m[2]))
    elif native == 'zypper':
        ok, out, err = run(['zypper', '--non-interactive', 'search', '--details', query], 70)
        if ok:
            for line in out.splitlines():
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 4 and package_id_ok(parts[1]):
                    found.append(record('RPM',parts[1],parts[1],parts[3],detail='openSUSE'))
    elif native == 'apt-get':
        ok, out, err = run(['apt-cache', 'search', '--names-only', query], 60)
        if ok:
            for line in out.splitlines():
                name, sep, description = line.partition(' - ')
                if sep and package_id_ok(name): found.append(record('DEB',name,name,detail=description))
    elif native == 'pacman':
        ok, out, err = run(['pacman', '-Ss', query], 60)
        if ok:
            for line in out.splitlines():
                if not line or line.startswith(' '): continue
                bits = line.split()
                if len(bits) >= 2 and '/' in bits[0]:
                    name = bits[0].split('/', 1)[1]
                    if package_id_ok(name): found.append(record('Arch',name,name,bits[1],bits[0].split('/')[0]))
    ok, out, _ = run(['snap', 'find', query], 60)
    if ok:
        for line in out.splitlines()[1:]:
            bits = line.split()
            if len(bits) >= 2 and package_id_ok(bits[0]):
                found.append(record('Snap', bits[0], bits[0], bits[1]))
    # Portable read-only discovery adapters (no native installs triggered).
    from portable_managers import search_extra
    extras, extra_warnings = search_extra(run, manager, query)
    found.extend(extras)
    warnings.extend(extra_warnings)
    for title, lookup in (('Flathub', flathub_lookup), ('GitHub', github_lookup)):
        if lookup is None: continue
        try: found.extend(lookup(query))
        except Exception as exc: warnings.append(f'{title} online search unavailable: {str(exc)[:160]}')
    unique = {}
    for item in found:
        unique[(item['kind'], item['id'], item['scope'])] = item
    return sorted(unique.values(), key=lambda x:(x['name'].casefold(),x['kind'])),warnings


def scan_updates(run, manager, github_lookup=None, checked=None, flatpak_scopes=None):
    found, notes = [], []
    # Check every installed Flatpak location, including named installations.
    scopes = flatpak_scopes if flatpak_scopes is not None else ('user', 'system')
    for scope in scopes:
        if scope == 'user': flag = '--user'
        elif scope == 'system': flag = '--system'
        elif package_id_ok(scope): flag = '--installation=' + scope
        else: continue
        ok, out, err = run(['flatpak','remote-ls',flag,'--updates','--app',
                            '--columns=application,version'], 70)
        if ok:
            if checked is not None: checked.add(('Flatpak', scope))
            for line in out.splitlines():
                p = line.split('\t')
                if len(p) >= 2 and package_id_ok(p[0].strip()):
                    found.append(record('Flatpak',p[0].strip(),p[0].strip(),p[1].strip(),scope))
        else:
            # One unhealthy remote should not hide available updates from healthy
            # remotes in the same installation. Fail closed for "up-to-date" status
            # unless every configured remote was checked successfully.
            rem_ok, rem_text, rem_err = run(['flatpak', 'remotes', flag, '--columns=name'], 20)
            remotes = [s.strip() for s in rem_text.splitlines() if package_id_ok(s.strip())] if rem_ok else []
            successful = 0
            for remote in remotes:
                remote_ok, remote_out, remote_err = run(
                    ['flatpak', 'remote-ls', flag, '--updates', '--app',
                     '--columns=application,version', remote], 70)
                if remote_ok:
                    successful += 1
                    for line in remote_out.splitlines():
                        parts = line.split('\t')
                        if len(parts) >= 2 and package_id_ok(parts[0].strip()):
                            found.append(record('Flatpak', parts[0].strip(), parts[0].strip(),
                                                parts[1].strip(), scope))
                else:
                    notes.append('Flatpak ' + scope + '/' + remote + ': ' + str(remote_err)[-140:])
            if remotes and successful == len(remotes) and checked is not None:
                checked.add(('Flatpak', scope))
            if not remotes:
                notes.append('Flatpak ' + scope + ': update check failed: ' + str(err)[-150:])
                if not rem_ok: notes.append('Flatpak ' + scope + ': remote list unavailable: ' + str(rem_err)[-120:])
    rpm_manager = manager('RPM')
    if rpm_manager in ('dnf','dnf5'):
        ok,out,err = run([rpm_manager,'check-upgrade'],90)
        # check-upgrade explicitly returns 100 if updates are available.
        # The runner marks that return value as non-success while preserving stdout.
        if checked is not None and (ok or (out.strip() and not err.strip())):
            checked.add(('RPM', ''))
        for line in out.splitlines():
            parts=line.split()
            if len(parts) >= 3 and '.' in parts[0]:
                name=parts[0].rsplit('.',1)[0]
                if package_id_ok(name): found.append(record('RPM', name, name, parts[1]))
    elif rpm_manager == 'zypper':
        ok,out,err=run(['zypper','--non-interactive','list-updates'],90)
        if ok:
            if checked is not None: checked.add(('RPM', ''))
            for line in out.splitlines():
                p=[v.strip() for v in line.split('|')]
                if len(p)>=5 and package_id_ok(p[2]): found.append(record('RPM',p[2],p[2],p[4]))
    elif rpm_manager == 'rpm-ostree':
        if checked is not None: checked.add(('RPM', 'system_updater'))
        notes.append('rpm-ostree OS updates are managed separately; no app-only RPM update list is available.')
    if manager('DEB') == 'apt-get':
        ok,out,err=run(['apt','list','--upgradable'],70)
        if ok:
            if checked is not None: checked.add(('DEB', ''))
            for line in out.splitlines():
                m=re.match(r'^([^/\s]+)/\S+\s+([^\s]+)',line)
                if m and package_id_ok(m[1]): found.append(record('DEB',m[1],m[1],m[2]))
    if manager('Arch') == 'pacman':
        # pacman -Qu uses the already synced package database (no implicit -Sy).
        ok,out,err=run(['pacman','-Qu'],50)
        if ok:
            if checked is not None: checked.add(('Arch', ''))
            for line in out.splitlines():
                m=re.match(r'^([^\s]+)\s+\S+\s+->\s+(\S+)',line)
                if m and package_id_ok(m[1]): found.append(record('Arch',m[1],m[1],m[2]))
        notes.append('Arch updates reflect the last synchronized package database; use the system updater for full upgrades.')
    ok,out,err=run(['snap','refresh','--list'],60)
    if ok or 'no updates available' in (str(err) + str(out)).lower() or 'all snaps up to date' in (str(err) + str(out)).lower():
        if checked is not None: checked.add(('Snap', ''))
        for line in out.splitlines()[1:]:
            parts=line.split()
            if len(parts)>=2 and package_id_ok(parts[0]): found.append(record('Snap',parts[0],parts[0],parts[1]))
    if github_lookup is not None:
        try:
            github_rows, github_notes=github_lookup()
            found.extend(github_rows)
            notes.extend(github_notes)
        except Exception as exc:
            notes.append('GitHub update check unavailable: ' + str(exc)[:160])
    if manager('APK') == 'apk':
        notes.append('Alpine APK packages: use the native system updater; per-package updates are not enabled.')
    if manager('XBPS') == 'xbps-query':
        notes.append('Void XBPS packages: use the native system updater; per-package updates are not enabled.')
    if manager('Portage') == 'emerge':
        notes.append('Gentoo Portage: use the distribution updater; native package transaction support is not implemented.')
    if manager('Nix') == 'nix':
        notes.append('NixOS: use your declarative configuration/flake or profile workflow.')
    notes.append('AppImages without an explicit GitHub source link cannot be checked for publisher updates.')
    unique={}
    for row in found: unique[(row['kind'],row['id'],row['scope'])]=row
    return sorted(unique.values(), key=lambda x:(x['name'].casefold(),x['kind'])),notes


def upgrade_command(entry, manager):
    kind,pid=entry['kind'],entry['id']
    if not package_id_ok(pid): return None
    if kind == 'Flatpak':
        scope=entry.get('scope')
        if scope in ('user', 'system'): flag = '--' + scope
        elif package_id_ok(scope): flag = '--installation=' + scope
        else: return None
        return ['flatpak','update','--app',flag,'--noninteractive','-y',pid]
    if kind == 'RPM':
        mgr=manager('RPM')
        if mgr in ('dnf','dnf5'): return ['pkexec',mgr,'upgrade','-y',pid]
        if mgr=='zypper': return ['pkexec','zypper','--non-interactive','update',pid]
    if kind == 'DEB' and manager('DEB')=='apt-get':
        return ['pkexec','apt-get','install','--only-upgrade','--no-remove','-y',pid]
    if kind == 'Arch' and manager('Arch')=='pacman':
        # A single-package upgrade risks an unsupported partial Arch upgrade.
        return None
    if kind == 'Snap' and manager('Snap')=='snap':
        return ['pkexec','snap','refresh',pid]
    return None


def install_command(entry, manager):
    kind,pid=entry['kind'],entry['id']
    if not package_id_ok(pid): return None
    if kind == 'Flatpak':
        remote=entry.get('remote','')
        if not package_id_ok(remote): return None
        return ['flatpak','install','--user','--noninteractive','-y',remote,pid]
    if kind == 'RPM':
        mgr=manager('RPM')
        if mgr=='rpm-ostree': return ['rpm-ostree','install',pid]
        if mgr in ('dnf','dnf5'): return ['pkexec',mgr,'install','-y',pid]
        if mgr=='zypper': return ['pkexec','zypper','--non-interactive','install',pid]
    if kind == 'DEB' and manager('DEB')=='apt-get': return ['pkexec','apt-get','install','-y',pid]
    if kind == 'Arch' and manager('Arch')=='pacman': return ['pkexec','pacman','-S','--noconfirm',pid]
    if kind == 'Snap' and manager('Snap')=='snap': return ['pkexec','snap','install',pid]
    return None


def export_manifest(entries, distro):
    packages=[]
    for entry in entries:
        kind=entry.get('kind','')
        pid=entry.get('id','')
        if kind in KINDS and (package_id_ok(pid) or kind=='AppImage'):
            packages.append(dict(kind=kind,id=pid,name=str(entry.get('name',pid)),
                                 scope=str(entry.get('scope','')),remote=str(entry.get('remote',''))))
    return {'format':'universal-linux-center-package-list','schema':1,
            'created_utc':datetime.now(timezone.utc).isoformat(),
            'host_distro':sorted(str(x) for x in distro),
            'contains_personal_files':False,'packages':packages}


def import_manifest(raw):
    if isinstance(raw, bytes):
        if len(raw)>2_000_000: raise ValueError('Backup exceeds 2MB limit')
        raw=raw.decode('utf-8')
    data=json.loads(raw)
    if not isinstance(data,dict) or data.get('format')!='universal-linux-center-package-list' or data.get('schema')!=1:
        raise ValueError('Not a supported package list backup')
    entries=data.get('packages')
    if not isinstance(entries,list) or len(entries)>10000: raise ValueError('Invalid package list')
    clean=[]
    for entry in entries:
        if not isinstance(entry,dict) or entry.get('kind') not in KINDS: raise ValueError('Invalid package type')
        kind=entry['kind']; pid=entry.get('id')
        if not isinstance(pid,str) or len(pid)>255 or (kind!='AppImage' and not package_id_ok(pid)):
            raise ValueError('Unsafe package identifier')
        remote=entry.get('remote','')
        if not isinstance(remote,str) or len(remote)>200 or (remote and not package_id_ok(remote)):
            raise ValueError('Invalid remote')
        clean.append(dict(kind=kind,id=pid,name=str(entry.get('name',pid))[:200],
                          scope=str(entry.get('scope',''))[:80],remote=remote))
    return clean
