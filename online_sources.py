"""Conservative Flathub / public GitHub release integration.

No arbitrary scripts, package archives, or GitHub source trees are executed.
Only directly-published AppImage binaries are eligible for managed updates.
"""
import hashlib
import json
import os
import platform
import re
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from feature_tools import record, package_id_ok

API = 'https://api.github.com'
FLATHUB = 'https://flathub.org/api/v2/search'
REPO_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$')
MAX_JSON = 1_500_000
MAX_APPIMAGE = 2 * 1024 * 1024 * 1024
TRACKING_FILE = Path.home() / '.config' / 'universal-linux-software-manager' / 'github-appimages.json'


def valid_repo(repo):
    return isinstance(repo, str) and bool(REPO_RE.fullmatch(repo)) and '..' not in repo


def github_url(repo):
    if not valid_repo(repo):
        raise ValueError('Invalid GitHub repository')
    return f'https://github.com/{repo}'


def _json_request(url, payload=None, transport=None):
    """Bounded HTTPS requests to fixed official API hosts."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in ('api.github.com', 'flathub.org'):
        raise ValueError('Unapproved API host')
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = urllib.request.Request(url, data=data,
             headers={'User-Agent': 'Universal-Linux-Software-Manager/1.0',
                      'Accept': 'application/vnd.github+json' if parts.hostname == 'api.github.com' else 'application/json',
                      **({'Content-Type': 'application/json'} if data is not None else {})},
             method='POST' if data is not None else 'GET')
    response = (transport or urllib.request.urlopen)(req, timeout=12)
    with response as stream:
        if urllib.parse.urlsplit(stream.geturl()).hostname not in ('api.github.com', 'flathub.org'):
            raise ValueError('API redirected to another host')
        raw = stream.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON: raise ValueError('API response too large')
        return json.loads(raw.decode('utf-8'))


def flathub_search(query, fetch=None):
    """Search Flathub's public catalogue; Flatpak remains the installer."""
    if not 2 <= len(query.strip()) <= 80: return []
    data = (fetch or _json_request)(FLATHUB, {'query': query.strip(), 'filters': []})
    hits = data.get('hits', []) if isinstance(data, dict) else data
    if not isinstance(hits, list): return []
    entries = []
    for hit in hits[:30]:
        if not isinstance(hit, dict): continue
        # The website's response can include an AppStream entry under _source.
        info = hit.get('_source', hit)
        if not isinstance(info, dict): continue
        pid = info.get('app_id') or info.get('id') or ''
        if not package_id_ok(pid) or '.' not in pid: continue
        name = info.get('name')
        if isinstance(name, dict): name = name.get('en') or next(iter(name.values()), pid)
        entries.append(record('Flatpak', str(name or pid), pid, str(info.get('version') or ''),
                              'flathub', str(info.get('summary') or '')[:350]))
    return entries


def github_search(query, fetch=None):
    if not 2 <= len(query.strip()) <= 80: return []
    q = urllib.parse.urlencode({'q': query.strip() + ' in:name,description', 'per_page': 10})
    data = (fetch or _json_request)(f'{API}/search/repositories?{q}')
    entries = []
    for info in (data.get('items', []) if isinstance(data, dict) else [])[:10]:
        if not isinstance(info, dict): continue
        repo = info.get('full_name', '')
        if not valid_repo(repo) or info.get('archived'): continue
        name = info.get('name') or repo.split('/')[-1]
        detail = str(info.get('description') or '')[:350]
        if info.get('fork'): detail = '[FORK] ' + detail
        e = record('GitHub', name, repo, scope='GitHub Releases', detail=detail)
        e['url'] = github_url(repo)
        e['fork'] = bool(info.get('fork'))
        entries.append(e)
    return entries


def latest_github_release(repo, fetch=None):
    github_url(repo)
    data = (fetch or _json_request)(f'{API}/repos/{repo}/releases/latest')
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        raise ValueError('No stable GitHub release found')
    tag = data.get('tag_name')
    if not isinstance(tag, str) or not tag or len(tag)>140 or any(ord(c)<32 for c in tag):
        raise ValueError('Invalid release tag')
    url = data.get('html_url', '')
    if not isinstance(url,str) or not url.startswith(github_url(repo) + '/releases/'):
        raise ValueError('Unexpected GitHub release URL')
    return {'repo':repo, 'tag':tag, 'url':url, 'assets':data.get('assets', [])}


def choose_appimage(release, machine=None):
    """Fail closed when architecture or the asset choice is ambiguous."""
    arch = (machine or platform.machine()).lower()
    if arch in ('amd64',): arch = 'x86_64'
    if arch in ('arm64',): arch = 'aarch64'
    if arch not in ('x86_64','aarch64'): return None
    candidates = []
    for asset in release.get('assets', []):
        if not isinstance(asset, dict): continue
        name = asset.get('name','')
        if not isinstance(name,str) or not name.lower().endswith('.appimage'): continue
        lower = name.lower()
        if any(other in lower for other in ('armhf','armv7','i386','i686','win32','windows','darwin','macos')): continue
        if arch == 'x86_64' and any(other in lower for other in ('aarch64','arm64')): continue
        if arch == 'aarch64' and any(other in lower for other in ('x86_64','amd64','x64')): continue
        size = asset.get('size',0)
        if not isinstance(size,int) or not 0 < size <= MAX_APPIMAGE: continue
        url=asset.get('browser_download_url','')
        if not isinstance(url,str) or not url.startswith(github_url(release['repo'])+'/releases/download/'):
            continue
        candidates.append(asset)
    if len(candidates)!=1: return None
    return candidates[0]


def _safe_filename(repo, tag):
    if not valid_repo(repo) or not isinstance(tag,str): raise ValueError('Invalid release identity')
    def clean(s): return re.sub('[^A-Za-z0-9._-]', '_', s).strip('._-')[:65]
    return clean(repo.replace('/','-')) + '__' + clean(tag) + '.AppImage'



def parse_github_repository(value):
    """Accept only a GitHub repository root or an owner/repo pair, not arbitrary URLs."""
    if not isinstance(value, str):
        raise ValueError('Invalid GitHub repository')
    value = value.strip()
    if value.startswith('https://'):
        parts = urllib.parse.urlsplit(value)
        if (parts.hostname != 'github.com' or parts.username or parts.password
                or parts.port is not None or parts.query or parts.fragment):
            raise ValueError('Enter an official https://github.com/OWNER/REPO link')
        value = parts.path.strip('/')
    if value.endswith('.git'):
        value = value[:-4]
    github_url(value)
    return value


def guess_appimage_version(filename):
    """Offer an editable version hint, not an assertion of the file's provenance."""
    if not isinstance(filename, str) or not filename.lower().endswith('.appimage'):
        return ''
    matches = re.findall(r'(?<![0-9A-Za-z])v?(\d+(?:\.\d+){1,3})(?![0-9])',
                         filename, flags=re.IGNORECASE)
    return 'v' + matches[0] if len(matches) == 1 else ''


def semver_tuple(tag):
    """Comparable simple numeric tags; not a full SemVer parser. Unknown => None."""
    if not isinstance(tag, str):
        return None
    m = re.fullmatch(r'[vV]?(\d+(?:\.\d+){0,3})', tag)
    return tuple(map(int, m.group(1).split('.'))) if m else None


def link_existing_appimage(app_dir, filename, repo, current_tag, tracking_file=TRACKING_FILE):
    """Persist an EXPLICIT user-selected mapping without modifying any AppImage."""
    github_url(repo)
    if (not isinstance(filename, str) or Path(filename).name != filename
            or filename.startswith('.') or not filename.lower().endswith('.appimage')):
        raise ValueError('Invalid installed AppImage filename')
    if not isinstance(current_tag, str) or not re.fullmatch(r'v?\d+(?:\.\d+){1,3}', current_tag):
        raise ValueError('Enter the installed numeric version, e.g. v1.0.0')
    app = Path(app_dir) / filename
    if app.is_symlink() or not app.is_file():
        raise ValueError('Selected AppImage is not a regular installed file')
    # Previously installed versions may have been removed via the AppImage
    # tab or an external tool.  A stale mapping must not block relinking a
    # different, actually installed release of the same repository.
    tracked = prune_missing_tracked_appimages(app_dir, tracking_file)
    if repo in tracked and tracked[repo]['file'] != filename:
        raise ValueError('This GitHub repository is already linked to another AppImage')
    if any(item['file'] == filename and key != repo for key, item in tracked.items()):
        raise ValueError('This AppImage is already linked to another GitHub repository')
    tracked[repo] = {'file': filename, 'tag': current_tag, 'sha256': ''}
    save_tracked(tracked, tracking_file)
    return repo

def tracked_installs(path=TRACKING_FILE):
    try:
        raw = Path(path).read_bytes()
        if len(raw)>200_000: return {}
        data=json.loads(raw)
    except (OSError,ValueError,UnicodeError): return {}
    if not isinstance(data,dict): return {}
    valid={}
    for repo,e in data.items():
        if not valid_repo(repo) or not isinstance(e,dict): continue
        name=e.get('file','')
        if not isinstance(name,str) or Path(name).name!=name or not name.lower().endswith('.appimage') or name.startswith('.'): continue
        if not isinstance(e.get('tag'),str): continue
        valid[repo]={'file':name,'tag':e['tag'], 'sha256':str(e.get('sha256',''))}
    return valid


def save_tracked(tracked, path=TRACKING_FILE):
    path=Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.github-appimages-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(tracked,f,indent=2)
            f.flush();os.fsync(f.fileno())
        os.chmod(temp,0o600)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def prune_missing_tracked_appimages(app_dir, tracking_file=TRACKING_FILE):
    """Forget registry entries for names absent from a verified Applications folder.

    Deliberately keep existing names, even symlinks: this is *not* an installer
    cleanup or a source identity guessing mechanism.  Do not rewrite any data
    if the folder cannot be scanned (e.g. temporarily unavailable mount).
    """
    tracked = tracked_installs(tracking_file)
    folder = Path(app_dir)
    if not tracked or folder.is_symlink() or not folder.is_dir():
        return tracked
    try:
        with os.scandir(folder) as iterator:
            present_names = {entry.name for entry in iterator}
    except OSError:
        return tracked
    current = {repo: item for repo, item in tracked.items()
               if item['file'] in present_names}
    if len(current) != len(tracked):
        save_tracked(current, tracking_file)
    return current


def forget_removed_appimage(app_dir, filename, tracking_file=TRACKING_FILE):
    """After a successful AppImage tab uninstall, drop only its exact mapping.

    Refuse to change tracking if the named file/alias is still present.
    Updates calls the same retirement backend using a recovery_dir; it must NOT
    call this function in the middle of its transactional replacement.
    """
    folder = Path(app_dir)
    if (not isinstance(filename, str) or Path(filename).name != filename
            or filename.startswith('.') or not filename.lower().endswith('.appimage')):
        raise ValueError('Invalid AppImage filename')
    if os.path.lexists(folder / filename):
        raise ValueError('Cannot unlink GitHub source while AppImage still exists')
    tracked = tracked_installs(tracking_file)
    current = {repo: item for repo, item in tracked.items()
               if item['file'] != filename}
    if len(current) != len(tracked):
        save_tracked(current, tracking_file)
    return len(tracked) - len(current)


def github_updates(app_dir, fetch=None, tracking_file=TRACKING_FILE, checked=None):
    found, notes = [], []
    for repo, item in prune_missing_tracked_appimages(app_dir, tracking_file).items():
        local=Path(app_dir)/item['file']
        if local.is_symlink() or not local.is_file(): continue
        try:
            latest=latest_github_release(repo,fetch)
            old = semver_tuple(item['tag'])
            new = semver_tuple(latest['tag'])
            if latest['tag'] == item['tag'] or (old is not None and new is not None and
                                                (new + (0,) * (4-len(new))) <= (old + (0,) * (4-len(old)))):
                if checked is not None: checked.add(('GitHub', repo))
                continue
            if old is None or new is None:
                notes.append(f'{repo}: cannot compare release tags safely; open GitHub manually.')
                continue
            asset=choose_appimage(latest)
            if asset is None:
                notes.append(f'{repo}: new release {latest["tag"]}; no unambiguous compatible AppImage. Open GitHub manually.')
                continue
            if checked is not None: checked.add(('GitHub', repo))
            entry=record('GitHub',repo.split('/')[-1],repo,latest['tag'],'GitHub Releases')
            entry['release']=latest
            found.append(entry)
        except (ValueError,urllib.error.URLError,TimeoutError,OSError) as exc:
            notes.append(f'GitHub {repo}: {str(exc)[:120]}')
    return found,notes


def download_appimage(asset, repo, dest, opener=None):
    """Download only direct GitHub release assets; never execute the download."""
    release_path = github_url(repo) + '/releases/download/'
    url = asset.get('browser_download_url','')
    if not isinstance(url,str) or not url.startswith(release_path):
        raise ValueError('Untrusted download URL')
    size=asset.get('size')
    if not isinstance(size,int) or not 0 < size <= MAX_APPIMAGE: raise ValueError('Invalid download size')
    req=urllib.request.Request(url,headers={'User-Agent':'Universal-Linux-Software-Manager/1.0'})
    stream=(opener or urllib.request.urlopen)(req,timeout=30)
    count=0
    sha=hashlib.sha256()
    with stream as response, Path(dest).open('wb') as output:
        host=urllib.parse.urlsplit(response.geturl()).hostname or ''
        if not (host=='github.com' or host.endswith('.githubusercontent.com')):
            raise ValueError('GitHub download redirected to unapproved host')
        while True:
            block=response.read(1_048_576)
            if not block: break
            count+=len(block)
            if count > MAX_APPIMAGE or count > size: raise ValueError('Downloaded file exceeds declared size')
            sha.update(block);output.write(block)
        output.flush();os.fsync(output.fileno())
    if count != size: raise ValueError('Incomplete GitHub download')
    with Path(dest).open('rb') as f:
        header=f.read(24)
        if len(header)<24 or header[:4]!=b'\x7fELF':
            raise ValueError('Downloaded file is not an ELF executable')
        order='little' if header[5]==1 else 'big' if header[5]==2 else None
        if order is None: raise ValueError('Invalid ELF byte order')
        cpu=int.from_bytes(header[18:20],order)
        expected=62 if platform.machine().lower() in ('x86_64','amd64') else 183 if platform.machine().lower() in ('aarch64','arm64') else None
        if cpu!=expected: raise ValueError('Linux executable architecture mismatch')
    digest=asset.get('digest','')
    if isinstance(digest,str) and digest.startswith('sha256:') and digest[7:].lower()!=sha.hexdigest():
        raise ValueError('Publisher SHA256 does not match download')
    return sha.hexdigest()


def install_github_appimage(release, appimage_tab, tracking_file=TRACKING_FILE, downloader=None,
                            before_install=None, on_install_failure=None):
    """Stage new file first, then track it. Never overwrite an existing AppImage.

    Old version is intentionally kept: users may remove it manually. This avoids
    deleting a running or locally modified AppImage during an update.
    """
    asset=choose_appimage(release)
    if asset is None: raise ValueError('No single compatible direct .AppImage asset')
    destname=_safe_filename(release['repo'],release['tag'])
    with tempfile.TemporaryDirectory(prefix='ulsm-github-') as dirname:
        source=Path(dirname)/destname
        sha=(downloader or download_appimage)(asset,release['repo'],source)
        source.chmod(source.stat().st_mode | stat.S_IXUSR)
        try:
            # For switching package sources, this runs only after verification
            # of the complete GitHub asset, but before the AppImage is published.
            if before_install is not None:
                before_install()
            appimage_tab.appimage_install(source)
        except Exception as exc:
            if on_install_failure is not None:
                on_install_failure(exc)
            raise
    tracked=tracked_installs(tracking_file)
    tracked[release['repo']]={'file':destname,'tag':release['tag'],'sha256':sha}
    save_tracked(tracked,tracking_file)
    return destname
