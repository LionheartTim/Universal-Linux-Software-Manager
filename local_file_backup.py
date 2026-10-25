"""Create and restore local package-file backups, without running bundled scripts.

Unlike an application-inventory export, this archive contains the user-selected
original installation files. It does not promise that a binary will work on a
nonmatching Linux distribution or that all dependencies are self-contained.
"""
import hashlib
import json
import os
import platform
import re
import stat
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

FORMAT = 'ulsm-local-install-files'
SCHEMA = 1
MAX_FILES = 100
MAX_ONE = 3 * 1024**3
MAX_TOTAL = 16 * 1024**3
MAX_SETTINGS = 110 * 1024**2
CHUNK = 1024 * 1024
EXTENSIONS = (
    ('.pkg.tar.zst', 'Arch'), ('.pkg.tar.xz', 'Arch'), ('.pkg.tar.gz', 'Arch'),
    ('.appimage', 'AppImage'), ('.flatpak', 'Flatpak'),
    ('.rpm', 'RPM'), ('.deb', 'DEB'), ('.snap', 'Snap'),
)


def package_type(name):
    if not isinstance(name, str) or '/' in name or '\\' in name or '\x00' in name:
        return None
    return next((kind for ext, kind in EXTENSIONS if name.casefold().endswith(ext)), None)


def _regular(path):
    p = Path(path)
    mode = p.lstat().st_mode
    if not stat.S_ISREG(mode) or p.is_symlink():
        raise ValueError('Only regular package files may be backed up (no symbolic links).')
    return p


def _header_ok(path, kind):
    with Path(path).open('rb') as f:
        head = f.read(16)
    if kind == 'AppImage': return head.startswith(b'\x7fELF')
    if kind == 'RPM': return head.startswith(b'\xed\xab\xee\xdb')
    if kind == 'DEB': return head.startswith(b'!<arch>\n')
    if kind == 'Snap': return head.startswith(b'hsqs')
    if kind == 'Arch':
        low = Path(path).name.casefold()
        return (head.startswith(b'\x28\xb5\x2f\xfd') if low.endswith('.zst') else
                head.startswith(b'\xfd7zXZ\x00') if low.endswith('.xz') else
                head.startswith(b'\x1f\x8b'))
    return bool(head)  # Flatpak's bundle format is validated by Flatpak at install.


def validate_source(path):
    p = _regular(path)
    kind = package_type(p.name)
    if not kind: raise ValueError('Unsupported package file: ' + p.name)
    size = p.stat().st_size
    if size <= 0 or size > MAX_ONE: raise ValueError('Empty or oversized package: ' + p.name)
    if not _header_ok(p, kind): raise ValueError('File header does not match extension: ' + p.name)
    return kind, size


def _digest_stream(source, output=None, limit=MAX_ONE):
    h, n = hashlib.sha256(), 0
    while True:
        block = source.read(CHUNK)
        if not block: break
        n += len(block)
        if n > limit: raise ValueError('File exceeds backup safety limit')
        h.update(block)
        if output is not None: output.write(block)
    return n, h.hexdigest()


def create_backup(destination, paths, settings_zip=None, source_desktop=None, source_distro=()):
    """Atomically create one portable ZIP; optionally embed a settings ZIP."""
    selected = [Path(p) for p in paths]
    if not selected and settings_zip is None: raise ValueError('Drop a package or select settings.')
    if len(selected) > MAX_FILES: raise ValueError('Too many package files')
    items, total = [], 0
    for p in selected:
        kind, size = validate_source(p)
        total += size
        if total > MAX_TOTAL: raise ValueError('Total package size exceeds 16 GiB')
        if any(e['filename'] == p.name for e in items):
            raise ValueError('Duplicate file name: ' + p.name)
        items.append({'filename':p.name, 'kind':kind, 'size':size})
    settings = Path(settings_zip) if settings_zip is not None else None
    if settings:
        settings = _regular(settings)
        if settings.stat().st_size > MAX_SETTINGS: raise ValueError('Settings archive is too large')
    manifest = {'format':FORMAT, 'schema':SCHEMA,
                'created_utc':datetime.now(timezone.utc).isoformat(),
                'architecture':platform.machine(),
                'desktop':str(source_desktop or ''),
                'distro':sorted(map(str, source_distro)),
                'packages':items, 'settings':None, 'encrypted':False}
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, stage = tempfile.mkstemp(prefix='.ulsm-backup-', suffix='.partial', dir=dest.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(stage, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for index, (p, item) in enumerate(zip(selected, items)):
                member=f'packages/{index}'
                before=p.stat()
                with p.open('rb') as source, archive.open(member, 'w', force_zip64=True) as target:
                    copied, sha = _digest_stream(source, target)
                after=p.stat()
                if copied != item['size'] or before.st_mtime_ns != after.st_mtime_ns or before.st_size != after.st_size:
                    raise ValueError('Package changed while backing up: ' + p.name)
                item.update(member=member, sha256=sha)
            if settings:
                with settings.open('rb') as source, archive.open('settings.zip','w',force_zip64=True) as target:
                    size, sha = _digest_stream(source, target, MAX_SETTINGS)
                manifest['settings']={'member':'settings.zip', 'size':size, 'sha256':sha}
            archive.writestr('manifest.json',json.dumps(manifest,indent=2,ensure_ascii=False))
        with open(stage,'rb') as f: os.fsync(f.fileno())
        os.replace(stage,dest)
    finally:
        if os.path.exists(stage): os.unlink(stage)
    return manifest


def inspect_backup(path):
    """Check entire archive hashes, sizes and exact expected member names."""
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist()
        names=[i.filename for i in entries]
        if len(names)!=len(set(names)) or len(names)>MAX_FILES+2:
            raise ValueError('Duplicate or unexpected archive entries')
        if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size>2_000_000:
            raise ValueError('Invalid backup manifest')
        meta=json.loads(archive.read('manifest.json'))
        if meta.get('format')!=FORMAT or meta.get('schema')!=SCHEMA:
            raise ValueError('Unsupported package-file backup')
        packages=meta.get('packages')
        if not isinstance(packages,list) or len(packages)>MAX_FILES:
            raise ValueError('Invalid package list')
        expected={'manifest.json'}
        total=0
        known=set()
        for i,item in enumerate(packages):
            if not isinstance(item,dict): raise ValueError('Invalid package record')
            name=item.get('filename','')
            if package_type(name)!=item.get('kind') or name in known or not name or Path(name).name != name:
                raise ValueError('Invalid package filename or format')
            known.add(name)
            member=f'packages/{i}'
            if item.get('member')!=member or member not in names:
                raise ValueError('Missing archive package')
            info=archive.getinfo(member)
            if info.is_dir() or info.file_size!=item.get('size') or info.file_size<=0 or info.file_size>MAX_ONE:
                raise ValueError('Invalid package size')
            total += info.file_size
            if total>MAX_TOTAL: raise ValueError('Backup is too large')
            with archive.open(member) as source:
                n,sha=_digest_stream(source)
            if n!=info.file_size or sha!=item.get('sha256'):
                raise ValueError('Package checksum mismatch: '+name)
            expected.add(member)
        settings=meta.get('settings')
        if settings is not None:
            if not isinstance(settings,dict) or settings.get('member')!='settings.zip' or 'settings.zip' not in names:
                raise ValueError('Invalid settings payload')
            info=archive.getinfo('settings.zip')
            if info.is_dir() or info.file_size>MAX_SETTINGS or info.file_size!=settings.get('size'):
                raise ValueError('Invalid settings backup size')
            with archive.open('settings.zip') as source:
                n,sha=_digest_stream(source,limit=MAX_SETTINGS)
            if n!=info.file_size or sha!=settings.get('sha256'):
                raise ValueError('Settings backup checksum mismatch')
            expected.add('settings.zip')
        if set(names)!=expected:
            raise ValueError('Unexpected archive member')
        return meta


def extract_package(archive_path,index,target_dir,manifest=None):
    manifest=manifest or inspect_backup(archive_path)
    item=manifest['packages'][index]
    dest=Path(target_dir)/item['filename']
    root=Path(target_dir)
    if root.is_symlink() or dest.is_symlink() or not root.is_dir():
        raise ValueError('Unsafe extraction location')
    if dest.exists(): raise ValueError('Package already staged')
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open(item['member']) as source, dest.open('xb') as target:
            n,sha=_digest_stream(source,target)
    if n!=item['size'] or sha!=item['sha256']:
        dest.unlink(missing_ok=True)
        raise ValueError('Package checksum mismatch')
    if item['kind']=='AppImage': dest.chmod(0o700)
    if not _header_ok(dest,item['kind']):
        dest.unlink(missing_ok=True)
        raise ValueError('Invalid package signature')
    return dest


def extract_settings(archive_path,target_dir,manifest=None):
    manifest=manifest or inspect_backup(archive_path)
    if manifest.get('settings') is None: raise ValueError('No settings in archive')
    root=Path(target_dir)
    if root.is_symlink() or not root.is_dir(): raise ValueError('Unsafe extraction directory')
    dest=root/'settings.zip'
    with zipfile.ZipFile(archive_path) as z:
        with z.open('settings.zip') as src, dest.open('xb') as dst:
            n,sha=_digest_stream(src,dst,MAX_SETTINGS)
    if n!=manifest['settings']['size'] or sha!=manifest['settings']['sha256']:
        dest.unlink(missing_ok=True)
        raise ValueError('Settings checksum mismatch')
    return dest
