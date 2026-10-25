# Online Discover — read-only test guide (v1.0.0)

This is a development preview for real-world GUI testing on Bazzite. Do not
publish a final distribution bundle until tests are complete.

## Build and start (in your extracted project folder)

```bash
flatpak-builder --user --install --install-deps-from=flathub --force-clean \
  --disable-cache --disable-rofiles-fuse --state-dir=.flatpak-builder-6.11 \
  build-6.11 io.github.LionheartTim.UniversalLinuxSoftwareManager.json \
  && flatpak run io.github.LionheartTim.UniversalLinuxSoftwareManager
```

## Discover tests — no installation or file downloads

1. Search **Audacity**. Select the GitHub result and click its **Name**. A list of
   stable releases should appear. Select an older release such as 3.7.9 and use
   **Open release on GitHub**; no installation dialog should appear.
2. Search **SpaghettiKart**. Click its GitHub result and select any available
   release. Its release page should open regardless of whether it offers a ZIP,
   AppImage, or other asset. Discover must never attempt to download or install it.
3. Select a GitHub repository result and click **Open project page**. Confirm it
   opens the project's GitHub repository, not a guessed third-party URL.
4. Search **VLC**. For a Flathub-sourced result, **Open project page** should
   open Flathub's app page. Click its **Name** to show build history, if the remote
   provides it, and use **Copy build ID** on a selected commit. Confirm it merely
   copies text to the clipboard; no Flatpak rollback or update should start.
5. For a native RPM, DEB, Arch or Snap result, where available, check that an
   unsupported project URL is **disabled**. The package ID stays visible for
   the user to locate an official source independently.
6. Check adjustable column widths, single-click-to-history, sorting, and
   search cancellation/warnings. Try temporary loss of network connectivity.

## Regression tests outside Discover

7. Package tabs retain their independent install/remove workflows.
8. Updates reads the installed application inventory and offers updates only
   when its existing known update source supports them. Flatpak USER and SYSTEM
   scope must remain separate.
9. Backup / Restore and progress indicators continue to work normally.
10. Keep the version at 1.0.0 and do not generate the public bundle yet.

Note: GitHub project search results are not automatically trustworthy. Inspect the
publisher and repository before choosing to download and install software yourself.

## Manual AppImage source / isolated remote tests

11. In **Updates**, select a manually installed `reblue-1.0.0-x86_64.appimage` row. Click **Link GitHub source** and enter `https://github.com/zolaware/reblue`. Confirm the suggested installed version `v1.0.0` and the repository. This does not touch the AppImage itself.
12. Click **Check for updates**. Reblue should show its **stable v1.3.1** release (if unchanged); nightly/prerelease builds must not be selected. **Update selected** only after reviewing the source and confirmation. After a successful, confirmed replacement, the old AppImage and its managed launcher are removed.
13. Verify the user Flatpak error for `claude-desktop` remains visible, but an available update from healthy Flathub can still be listed. The broken remote must NOT silently be marked healthy or have GPG verification disabled.
14. Confirm **Discover stays read-only** and contains no installation controls.

## GUI regression: non-editable information tables

15. Double-click cells in **Updates** (including Status, Installed, Package ID) and **Discover**. The text must never turn into an editor or accept typed changes. F2 must not edit either table.
16. **Discover**: single-click a name to show version history; change column widths and sort results as before.
17. **Updates**: select Reblue to verify **Link GitHub source** and **Update selected** remain driven by the selection and status. Do not install updates just for this test.
18. **Backup / Restore**: import a safe application-list JSON and verify that double-clicking table cells cannot alter the manifest shown. No restore needed.


## GitHub AppImage safe replacement GUI validation (v1.0.0)

- [ ] On Updates, select linked `reblue-1.0.0-x86_64.appimage` with the stable `v1.3.1` update.
- [ ] Click Update selected. No removal popup should appear **before download and verification**.
- [ ] After download, the dialog explains the old and new filenames/versions and defaults to **No**.
- [ ] Choose No: the old binary and tracked v1.0.0 remain; no new AppImage is installed.
- [ ] Repeat and choose Yes: the new AppImage installs and works before old executable bytes are removed.
- [ ] Check the OLD pathname and its managed launcher are gone entirely; no symlink or duplicate KDE menu item remains.
- [ ] Confirm Updates now shows the new version and no stale update; AppImage lists only the new executable.
- [ ] On a controlled failure (network, wrong checksum, destination already present), the old executable still works.
- [ ] Check that manually installed AppImages without an explicit GitHub link are still not blindly updated.
- [ ] Remember these are interactive Bazzite checks; no real Flatpak build or GitHub download was run in this test environment.


### Shared AppImage removal handler — post-update regression

- AppImage and Updates now use the same guarded remove backend. A successful
  GitHub update removes the old exact AppImage filename and managed launcher,
  leaving only the new binary and its launcher. There is **no compatibility symlink**.
- A failing download, new install, old launcher removal, or registry save must
  leave the previous AppImage and launcher available, without publishing a
  duplicate. Test in Bazzite before distributing.
- If the previous test build left `reblue-1.0.0-x86_64.appimage` as a
  compatibility symlink, select that **old** entry in the AppImage tab and use
  Uninstall selected. The shared backend now recognizes only a local alias to
  a regular AppImage in `~/Applications` and removes just the alias and exact
  managed old shortcut; the actual v1.3.1 image is not touched.
- Standard Flatpak package updates continue through the Flatpak backend; no
  uninstall/reinstall is performed.


### Bazzite regression: EXDEV when removing an AppImage launcher

- The manager must not attempt to move a KDE launcher from
  `~/.local/share/applications` to `~/Applications` if the locations reside
  on different filesystems. A private rollback folder next to the launcher
  is used if `os.replace` fails with `errno.EXDEV`.
- Select the OLD `reblue-1.0.0-x86_64.appimage` only. Remove it from the
  AppImage tab after reviewing the prompt. The updated v1.3.1 must remain.
- Confirm the old KDE launcher disappears and the current v1.3.1 launcher
  still starts correctly.
- Repeat the test with a simulated EXDEV failure: both direct removal and
  update retirement must work, while other errors roll back safely.
- The test run does NOT alter real files on the Bazzite host.


### Reblue regression: obsolete GitHub link (new fix)

- [ ] Starting with Reblue 1.0.0 newly installed after removing Reblue 1.3.1, open **Updates**. An obsolete record referencing a *missing* 1.3.1 filename should be discarded automatically when the directory can be scanned.
- [ ] Select `reblue-1.0.0-x86_64.appimage`, click **Link GitHub source**, enter `https://github.com/zolaware/reblue` and confirm `v1.0.0`. The previous **already linked to another AppImage** error must not occur.
- [ ] Check that the stable v1.3.1 is offered again after refreshing. Do **not** install anything until the source/version are verified.
- [ ] In **AppImage**, remove a disposable, GitHub-linked AppImage through **Uninstall selected**. Its local GitHub mapping must disappear only after successful file removal. Other linked AppImages must keep their mappings.
- [ ] If an AppImage file still exists (including an old symlink), the app must not silently drop its association merely because the filename looks old; the file must be explicitly removed first.
- [ ] No developer terminal deletion of the tracking JSON is necessary. This fix should not remove a real installed AppImage or disable update/source security checks.

## GUI regression: search-field clearing

19. **Updates**: run Check for updates and note the total installed package count. Type `reblue`; the visible rows should shrink to matching installed software. Delete the entire text (including via the clear/X control): all installed software should reappear **without fetching updates again**. Repeat with an unmatched term, then clear it.
20. **Updates**: enable `Updates available only`. Deleting the search term must show all *available updates only*, not every installed package; disable the checkbox to see all installed software again.
21. **Discover**: search `audacity` and confirm results. Delete the entire search term: old results and their Open project page action must disappear. Type `vlc`, press Search; only that new query's results should appear.
22. **Discover**: clear or edit the search field while a slow online lookup is still running. The late response must not restore results from the old query.


## Universal Backup / Restore test sequence

1. Open Backup / Restore on Bazzite. Verify the desktop is detected as KDE and choose **Installed applications** plus **Appearance**. Uncheck all but an unimportant test application.
2. Save to a local ZIP and open the backup. Confirm no online account is needed, the app list is accurate, and checked settings categories are shown.
3. For harmless appearance configuration only, choose Restore checked settings, approve the warning, then check that previous config files were saved under `restore-history`. Review KDE behavior after a new login.
4. Save with **Flatpak app preferences** explicitly enabled only after reviewing that they can contain private files. Never share this unencrypted archive publicly.
5. When using a different desktop, verify display/panel settings cannot restore; a selected Flatpak app preference may still be transferred separately.
6. In Updates/Discover on Alpine, Void, Gentoo and NixOS verify any native inventory/search is read-only and unsupported per-package upgrades are not offered. **These require actual tests on those distributions.**
