"""Capability-based read-only adapters for additional Linux package ecosystems.

System transactions are deliberately NOT run here: a distro's full-system
update tools must be used until a safe native transaction adapter is tested.
"""
import json
import re
from feature_tools import package_id_ok, record


def _split_pkgver(token, void=False):
    pattern = r'^(.+)-([0-9][^\s]*_\d+)$' if void else r'^(.+)-([0-9][^\s]*-r\d+)$'
    match = re.fullmatch(pattern, token)
    if match and package_id_ok(match[1]): return match[1], match[2]
    return None


def search_extra(run, manager, query):
    rows, messages = [], []
    if manager('APK') == 'apk':
        ok, out, err = run(['apk', 'search', '-v', query], 40)
        if ok:
            for line in out.splitlines():
                token, _, desc = line.partition(' - ')
                parsed = _split_pkgver(token.strip())
                if parsed: rows.append(record('APK', parsed[0], parsed[0], parsed[1], detail=desc))
        else: messages.append('Alpine APK search unavailable: ' + str(err)[-100:])
    if manager('XBPS') == 'xbps-query':
        ok, out, err = run(['xbps-query', '-Rs', query], 40)
        if ok:
            for line in out.splitlines():
                tokens=line.split()
                if len(tokens)<2: continue
                parsed = _split_pkgver(tokens[1], void=True)
                if parsed: rows.append(record('XBPS', parsed[0], parsed[0], parsed[1], detail=' '.join(tokens[2:])[:300]))
        else: messages.append('Void XBPS search unavailable: ' + str(err)[-100:])
    if manager('Portage') == 'emerge':
        ok, out, err = run(['emerge', '--search', query], 65)
        if ok:
            for line in out.splitlines():
                m = re.match(r'^\s*\*\s+([A-Za-z0-9+_.-]+)/([A-Za-z0-9+_.-]+)\s*$',line)
                if m and package_id_ok(m[2]):
                    rows.append(record('Portage',m[2],m[2],scope=m[1]))
        else: messages.append('Gentoo Portage search unavailable: '+str(err)[-100:])
    if manager('Nix') == 'nix':
        ok, out, err = run(['nix','search','nixpkgs',query,'--json'], 65)
        if ok:
            try:
                entries=json.loads(out)
                for attr, item in list(entries.items())[:150]:
                    if not isinstance(item,dict): continue
                    name=attr.split('.')[-1]
                    if package_id_ok(name):
                        rows.append(record('Nix',item.get('pname',name),name,
                            item.get('version',''),scope='nixpkgs',detail=item.get('description','')))
            except (ValueError,AttributeError):
                messages.append('Nix search returned an unsupported response.')
        else: messages.append('Nix search requires available nixpkgs source: '+str(err)[-100:])
    return rows,messages


def installed_extra(run, manager):
    rows, messages = [], []
    if manager('APK') == 'apk':
        ok, out, err = run(['apk', 'info', '-v'], 40)
        if ok:
            for line in out.splitlines():
                parsed = _split_pkgver(line.strip())
                if parsed: rows.append(record('APK',parsed[0],parsed[0],parsed[1],'SYSTEM'))
        else: messages.append('Alpine installed APK list unavailable: ' + str(err)[-100:])
    if manager('XBPS') == 'xbps-query':
        ok, out, err = run(['xbps-query','-l'], 40)
        if ok:
            for line in out.splitlines():
                tokens=line.split()
                if len(tokens)<2 or tokens[0]!='ii': continue
                parsed=_split_pkgver(tokens[1], void=True)
                if parsed: rows.append(record('XBPS',parsed[0],parsed[0],parsed[1],'SYSTEM'))
        else: messages.append('Void installed XBPS list unavailable: ' + str(err)[-100:])
    if manager('Portage') == 'emerge':
        ok,out,_=run(['qlist','-ICv'],40)
        if ok:
            for line in out.splitlines():
                token=line.strip().split()[0] if line.strip() else ''
                m=re.match(r'^([A-Za-z0-9+_.-]+)/(.+)-([0-9][^\s]*)$',token)
                if m and package_id_ok(m[2]):
                    rows.append(record('Portage',m[2],m[2],m[3],scope=m[1]))
        else: messages.append('Gentoo: install portage-utils (qlist) for a partial package inventory.')
    if manager('Nix') == 'nix':
        ok,out,_=run(['nix','profile','list','--json'],40)
        if ok:
            try:
                data=json.loads(out)
                entries=data.get('elements',{})
                for key,entry in entries.items():
                    if not isinstance(entry,dict) or not entry.get('active',True): continue
                    name=key.rsplit('.',1)[-1].rsplit('#',1)[-1]
                    if package_id_ok(name):rows.append(record('Nix',name,name,scope='PROFILE'))
            except (ValueError,AttributeError): messages.append('Nix: profile inventory could not be parsed.')
        messages.append('Nix: only the active user profile is listed; NixOS declarations and other profiles are not included.')
    return rows,messages
