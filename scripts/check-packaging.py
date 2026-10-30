#!/usr/bin/env python3
"""Fail the release build if Python runtime modules are omitted from Flatpak.

Check BEFORE building that all local .py modules are listed as sources and
installed into /app/bin. Optionally check the Flatpak Builder staging directory
AFTER building before creating the distributable .flatpak bundle.
"""
import argparse
import ast
import json
from pathlib import Path
import shlex
import sys


def _imports(path):
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.partition('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.partition('.')[0])
    return imports


def validate_manifest(data, root):
    """Return list of errors; every local Python module must ship in /app/bin."""
    module = data['modules'][0]
    errors = []
    paths = [entry['path'] for entry in module['sources'] if entry['type'] == 'file']
    source_paths = set(paths)
    installed = []
    for command in module['build-commands']:
        args = shlex.split(command)
        if len(args) >= 4 and args[0] == 'install' and args[1].startswith('-Dm'):
            installed.append((args[2], args[3]))
    python_files = sorted(f.name for f in root.glob('*.py'))
    names = {p[:-3] for p in python_files}
    for filename in python_files:
        expected_dest = f'/app/bin/{filename}'
        count = installed.count((filename, expected_dest))
        if filename not in source_paths:
            errors.append(f'{filename}: missing from Flatpak sources')
        if count != 1:
            errors.append(f'{filename}: expected exactly one install to {expected_dest}, found {count}')
        for dep in sorted(_imports(root / filename) & names):
            if dep + '.py' not in source_paths:
                errors.append(f'{filename} imports {dep}, but {dep}.py is not in Flatpak sources')
    for source, target in installed:
        if source.endswith('.py') and source not in python_files:
            errors.append(f'build command installs missing Python file: {source}')
        if source.endswith('.py') and source not in source_paths:
            errors.append(f'build command for {source} has no corresponding Flatpak source')
    return list(dict.fromkeys(errors))


def validate_staging(root, staging):
    """Check the builder's actual /app/bin tree, not only the manifest."""
    errors = []
    for filename in sorted(f.name for f in root.glob('*.py')):
        path = staging / 'files' / 'bin' / filename
        if not path.is_file() or path.stat().st_size == 0:
            errors.append(f'Flatpak staging missing/empty: {path}')
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('staging', nargs='?', type=Path)
    args = parser.parse_args(argv)
    manifest = args.manifest.resolve()
    root = manifest.parent
    errors = validate_manifest(json.loads(manifest.read_text(encoding='utf-8')), root)
    if args.staging is not None:
        errors.extend(validate_staging(root, args.staging.resolve()))
    if errors:
        print('FLATPAK PACKAGING FAILED:', file=sys.stderr)
        for msg in errors:
            print(' - ' + msg, file=sys.stderr)
        return 1
    print('Flatpak packaging check OK: all application Python modules included' +
          (' in staging' if args.staging is not None else ' in manifest'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
