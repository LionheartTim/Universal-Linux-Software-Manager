"""Bounded and read-only publisher version history for Discover.

GitHub release history is not a guarantee that an AppImage is offered for each
version. Flatpak history is OSTree commits, not semantic upstream versions.
No shell text is interpolated; commands are argument arrays only.
"""
import re
from online_sources import _json_request, valid_repo, github_url, choose_appimage
from feature_tools import package_id_ok

COMMIT_RE = re.compile(r"^[0-9a-f]{40,64}$", re.IGNORECASE)
MAX_GITHUB_PAGES = 3
GITHUB_PAGE_SIZE = 50
MAX_FLATPAK_COMMITS = 150


def github_release_history(repo, fetch=None, max_pages=MAX_GITHUB_PAGES):
    """List up to 150 published stable GitHub releases, newest first."""
    if not valid_repo(repo):
        raise ValueError('Unsafe GitHub repository name')
    getter = fetch or _json_request
    all_releases = []
    seen = set()
    complete = False
    for page in range(1, min(max_pages, MAX_GITHUB_PAGES) + 1):
        data = getter(f'https://api.github.com/repos/{repo}/releases?per_page={GITHUB_PAGE_SIZE}&page={page}')
        if not isinstance(data, list):
            raise ValueError('Unexpected GitHub releases response')
        for item in data:
            if not isinstance(item, dict) or item.get('draft') or item.get('prerelease'):
                continue
            tag = item.get('tag_name')
            url = item.get('html_url')
            if not isinstance(tag, str) or not 0 < len(tag) <= 140 or any(ord(c) < 32 for c in tag):
                continue
            if not isinstance(url, str) or not url.startswith(github_url(repo) + '/releases/'):
                continue
            if tag in seen:
                continue
            seen.add(tag)
            release = {'repo': repo, 'tag': tag, 'url': url,
                       'assets': item.get('assets') if isinstance(item.get('assets'), list) else []}
            published = item.get('published_at')
            all_releases.append({'version': tag, 'date': published[:10] if isinstance(published, str) else '',
                                 'release': release, 'installable': choose_appimage(release) is not None})
        if len(data) < GITHUB_PAGE_SIZE:
            complete = True
            break
    return all_releases, complete


def parse_flatpak_history(output, limit=MAX_FLATPAK_COMMITS):
    """Parse `flatpak remote-info --log` without trusting its human labels as version numbers."""
    records = []
    current = None
    for line in output.splitlines():
        m = re.match(r'^\s*Commit:\s*([0-9a-fA-F]{40,64})\s*$', line)
        if m:
            if current and current['commit'] not in {r['commit'] for r in records}:
                records.append(current)
            current = {'commit': m.group(1).lower(), 'subject': '', 'date': ''}
            if len(records) >= limit:
                break
            continue
        if current:
            m = re.match(r'^\s*(Subject|Date):\s*(.*)$', line)
            if m:
                current[m.group(1).lower()] = m.group(2).strip()[:200]
    if current and len(records) < limit and current['commit'] not in {r['commit'] for r in records}:
        records.append(current)
    return records[:limit]


def flatpak_history(run, remote, package_id):
    if not package_id_ok(remote) or not package_id_ok(package_id):
        raise ValueError('Unsafe Flatpak remote or package identifier')
    ok, out, err = run(['env', 'LC_ALL=C', 'flatpak', 'remote-info', '--log', '--app', remote, package_id], 90)
    if not ok:
        raise RuntimeError('Flatpak version history unavailable: ' + str(err)[-240:])
    return parse_flatpak_history(out)


def installed_user_flatpak_origin(run, package_id):
    if not package_id_ok(package_id):
        raise ValueError('Unsafe package identifier')
    ok, out, _ = run(['flatpak', 'info', '--user', '--show-origin', package_id], 20)
    return out.strip() if ok else None


def flatpak_revision_command(run, package_id, remote, commit):
    """Allow a revision change only for an already-installed USER Flatpak from the same remote."""
    if not package_id_ok(package_id) or not package_id_ok(remote) or not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        raise ValueError('Unsafe Flatpak rollback selection')
    if installed_user_flatpak_origin(run, package_id) != remote:
        return None
    return ['flatpak', 'update', '--user', '--app', '--noninteractive', '-y', '--commit=' + commit, package_id]


def discovery_project_url(entry):
    """Return a trustworthy *viewing* URL, never a download/installation command.

    Native repositories may have no canonical per-package web page; in that case
    return None rather than inventing a URL or silently searching an unrelated site.
    """
    if not isinstance(entry, dict):
        return None
    kind, package_id = entry.get('kind'), entry.get('id')
    if kind == 'GitHub':
        try:
            return github_url(package_id)
        except (TypeError, ValueError):
            return None
    if kind == 'Flatpak' and package_id_ok(package_id) and '.' in package_id:
        remotes = [r.strip().casefold() for r in str(entry.get('scope') or '').split(',')]
        if 'flathub' in remotes:
            return 'https://flathub.org/apps/' + package_id
    return None


def discovery_release_url(entry, version):
    """Accept only a GitHub release URL belonging to the chosen repository."""
    repo_url = discovery_project_url(entry)
    if not repo_url or entry.get('kind') != 'GitHub' or not isinstance(version, dict):
        return None
    release = version.get('release')
    if not isinstance(release, dict):
        return None
    url = release.get('url')
    if not isinstance(url, str) or not url.startswith(repo_url + '/releases/tag/'):
        return None
    # Reject URL control bytes and fragments/query tricks; the history fetcher
    # already validates this, but keep this boundary explicit for UI callers.
    if any(ord(c) < 32 or ord(c) == 127 for c in url) or '?' in url or '#' in url:
        return None
    return url
