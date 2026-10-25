# Universal Linux Software Manager v1.0.0 – build correction

The user's Bazzite build stopped at `Committing stage init to cache` with a
`flatpak-builder` segmentation fault and a warning that PyQt BaseApp 6.10 is EOL.

Changes:
- KDE Platform + SDK: 6.11
- PyQt BaseApp: 6.11 (matched to KDE branch)
- Separate state directory `.flatpak-builder-6.11` for building
- `--disable-cache` and `--disable-rofiles-fuse` to avoid previous cache and FUSE staging
- Updated local build steps and matching manifest regression assertions

The actual cause of the segmentation fault is **not proven**. No application
install/remove logic, user interface or Flatpak application ID was changed.
Version remains **1.0.0**. Rebuild and test on Bazzite.

To install and run the new build after extracting this ZIP:

```bash
flatpak-builder --user --install --install-deps-from=flathub --force-clean \
  --disable-cache --disable-rofiles-fuse --state-dir=.flatpak-builder-6.11 \
  build-6.11 io.github.LionheartTim.UniversalLinuxSoftwareManager.json
flatpak run io.github.LionheartTim.UniversalLinuxSoftwareManager
```

## AppImage removal cross-filesystem fix (Bazzite, 2026-10-24)

Previously, removing an old AppImage with a manager-owned KDE launcher could
fail with `[Errno 18] Invalid cross-device link`. The shared backend attempted
to move `~/.local/share/applications/*.desktop` to a quarantine directory in
`~/Applications`, but Bazzite can place these directories on different mounts.

The lifecycle backend now uses an atomic, private *sibling* recovery folder for
only those launcher moves that report `EXDEV`. It cleans up sibling recovery
folders after successful removal/update or a successful rollback. Updates and
AppImage Uninstall still share the same removal implementation, and no new
symlinks to the old AppImage name are created.

Testing: 128/128 automated tests passed, including five new cross-device cases
(direct removal, old symlink removal, successful update, registry failure
rollback, and failed fallback rollback). No live Bazzite Flatpak build or
host AppImage operation was performed here. Keep v1.0.0 in preview.


## Stale GitHub-AppImage association fix (Bazzite, 2026-10-24)

The prior AppImage uninstall retired the executable/launcher but could leave
`github-appimages.json` pointing to its now missing filename. Relinking the
same GitHub repository to a reinstalled older AppImage then failed.

- On standalone successful removal, clear only the removed AppImage's exact
  mapping. Transactional updates do not prematurely clear the mapping.
- On Updates scan and explicit source relinking, prune only mappings whose
  filenames are actually absent from the readable Applications directory.
  If the directory is unavailable, no mappings are dropped.
- No AppImage files are deleted during reconciliation; same-repository
  conflicts remain blocked when a different target file still exists.
- 136/136 network-free automated regression tests passed (8 additional tests).
- This was not yet built or tested in the Bazzite GUI.
