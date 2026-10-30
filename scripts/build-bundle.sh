#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ID='io.github.LionheartTim.UniversalLinuxSoftwareManager'
MANIFEST="$ID.json"
OUTPUT="${1:-UniversalLinuxSoftwareManager-v1.0.0.flatpak}"
if [[ -f "$OUTPUT" ]]; then
    echo "Output already exists: $OUTPUT (remove or rename it before building)" >&2
    exit 1
fi
command -v python3 >/dev/null || { echo "Python 3 is required" >&2; exit 1; }
python3 -m unittest discover -s tests -v
python3 scripts/check-packaging.py "$MANIFEST"
python3 -m py_compile *.py
python3 -m json.tool "$MANIFEST" >/dev/null
python3 -c 'import sys, xml.etree.ElementTree as ET; ET.parse(sys.argv[1])' "$ID.metainfo.xml"
if command -v desktop-file-validate >/dev/null; then
    desktop-file-validate "$ID.desktop"
else
    echo "WARNING: desktop-file-validate is not installed; desktop-entry lint skipped" >&2
fi
if command -v appstreamcli >/dev/null; then
    appstreamcli validate --explain "$ID.metainfo.xml"
else
    echo "WARNING: appstreamcli not installed; AppStream lint skipped" >&2
fi
command -v flatpak-builder >/dev/null || { echo "Install flatpak-builder first; static tests passed but bundle not built" >&2; exit 1; }
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
# Build in a separate Flatpak Builder state tree to avoid the existing 6.10
# staging cache. --disable-cache avoids reusing previous stage commits,
# --disable-rofiles-fuse avoids FUSE-based hardlink staging optimizations.
# These options are conservative workarounds for reported builder crashes;
# they do not establish the root cause of a segmentation fault.
BUILD_DIR="${ULSM_BUILD_DIR:-build-6.11}"
STATE_DIR="${ULSM_STATE_DIR:-.flatpak-builder-6.11}"
REPO_DIR="${ULSM_REPO_DIR:-local-repo-6.11}"
flatpak-builder --user --install-deps-from=flathub --force-clean \
    --disable-cache --disable-rofiles-fuse --state-dir="$STATE_DIR" \
    --repo="$REPO_DIR" "$BUILD_DIR" "$MANIFEST"
python3 scripts/check-packaging.py "$MANIFEST" "$BUILD_DIR"
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo \
    "$REPO_DIR" "$OUTPUT" "$ID"
echo "Built $OUTPUT"
echo 'Runtime is NOT included in a single-file bundle; it will be downloaded separately if missing.'
