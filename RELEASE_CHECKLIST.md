# Universal Linux Software Manager — Release checklist (v1.0.0 release candidate)

## Before release

- [ ] Review manifest host access (`--talk-name=org.freedesktop.Flatpak`) and filesystem permissions.
- [ ] Run `python3 -m unittest discover -s tests -v`.
- [ ] Run `python3 -m py_compile main.py`.
- [ ] Run `desktop-file-validate` and `appstreamcli validate --explain` where available.
- [ ] Build Flatpak using `bash scripts/build-bundle.sh` (requires Flatpak Builder and access to Flathub dependencies).
- [ ] Install and launch bundle on a clean test user or virtual machine.
- [ ] Check launcher, window icon, taskbar icon, 9 tabs, 16-block progress indicator and USER/SYSTEM/Status columns, and the Updates/Discover/Backup & Restore tabs.
- [ ] Verify closing window **during** a long-running package operation shows a warning and keeps it open.
- [ ] Verify AppImage succeeds and desktop launcher works; test interrupted copy with a large noncritical sample and check for `.partial` clean-up.
- [ ] Verify missing `pkexec` or package manager disables actions with an understandable reason.
- [ ] Verify Flatpak removal offers to keep user data (default); optional data deletion needs explicit selection.
- [ ] Validate RPM deferred status and reboot on Bazzite without modifying core packages.
- [ ] Test Debian/Ubuntu, Arch, Fedora, openSUSE, Snap workflows in isolated environments where available.
- [ ] Confirm appstream metadata, desktop entry and icons are present inside built app.
- [ ] Confirm GitHub feedback and bug links open correctly.
- [ ] State that this Flatpak bundle does not include its shared KDE Platform runtime.
- [ ] Build separate artifacts for desired CPU architectures.

## Unsupported native package families

NixOS/Nix, Alpine/apk, Gentoo/Portage, Void/XBPS are not yet native package-manager backends. Flatpak and AppImage may still be useful on these systems.

## Authorization and caution

`flatpak-spawn --host` executes host commands and requires powerful permission. The app is designed to show confirmation and fail closed where unsupported. Installation/uninstallation of system packages remains potentially destructive. Do not claim full cross-distribution validation based on static tests alone.

- [ ] Test Updates/Discover/Backup on Bazzite and representative RPM/DEB/Arch/Snap hosts.
- [ ] Confirm Discover can only open verified links or copy Flatpak build IDs, not install software. Verify independent install/update controls in their own tabs.

- [ ] Verify the GitHub repository rename and feedback discussion links are live before public release.
- [ ] Verify the new Flatpak ID installs separately from the old app; remove the old ID if no longer needed.

## Online Flathub / GitHub discovery — read-only regression checks

- [ ] Search `audacity` and `spaghetti kart`; show public GitHub repositories, if returned.
- [ ] Click a GitHub search-result name to view previous published releases and dates.
- [ ] Confirm **Open release on GitHub** opens the selected release page (including ZIP-only versions), without any download/install step in Discover.
- [ ] Confirm **Open project page** opens verified GitHub repository links.
- [ ] Search `vlc`; Flathub project-page links open `flathub.org/apps/<app-id>` for an unambiguous Flathub result.
- [ ] For Flatpak version history, **Copy build ID** copies the commit SHA and does not execute `flatpak update --commit`.
- [ ] Confirm no **Install latest version**, **Choose this version**, source-switch popup, installer job or package changes are accessible from Discover.
- [ ] For other repositories with no grounded project link, **Open project page** remains disabled rather than guessing a URL.
- [ ] Validate GitHub/Flathub networking errors are shown cleanly, and local package searches still work offline.
- [ ] Verify Updates and package-tab installations remain functional separately from Discover.
- [ ] Do not publish a distribution bundle until Bazzite GUI testing is complete.

- [ ] On Bazzite, double-clicking a cell in Updates, Discover, or Backup/Restore cannot edit the displayed text. Verify F2 also has no effect.
- [ ] Clicking a Discover name still opens version history, columns remain resizable, and Updates selection buttons still work.


- [ ] On Bazzite, verify GitHub AppImage updates **download and verify first**, then show the Yes/No *Replace old AppImage?* prompt (No default).
- [ ] Test Yes only with a noncritical AppImage; new copy must be valid before old executable is replaced by a compatibility symlink.
- [ ] Test No, interrupted download, tracking errors and a failed installation; old AppImage must remain usable.
- [ ] Confirm current v1.0.0 code on Bazzite before generating any official distributable bundle.


- [ ] Bazzite GUI: clearing Updates search restores full installed inventory without rechecking updates.
- [ ] Bazzite GUI: clearing/changing Discover search removes stale matches; a delayed GitHub/Flathub search does not put old matches back.


### New drag-and-drop local file backups (not yet verified on Bazzite)

- [ ] Drop a known harmless `.AppImage` into the backup table; confirm it is listed without any actual app-list scan.
- [ ] Drop `.flatpak`, `.rpm`, `.deb`, `.snap` and an Arch package (one at a time) and check format labeling. Reject fake extensions and `.flatpakref` pointers.
- [ ] Select a harmless KDE setting, create a local ZIP, and check that the saved ZIP contains the chosen bytes and optional settings.
- [ ] Open ZIP and reinstall an unimportant AppImage into `~/Applications`; verify KDE launcher.
- [ ] Confirm native RPM is not offered for Ubuntu and DEB is not offered for Fedora/Bazzite.
- [ ] Confirm wrong-architecture and tampered archives fail closed.
- [ ] Restore optional settings only after making a separate recovery backup.
- [ ] Confirm no install happens on drag/drop, ZIP creation or opening. Installation requires explicit consent.
- [ ] Verify busy/close guards and progress UI for large package files on Bazzite.
- [ ] Do not release public Flatpak until tests on Bazzite and an additional distro pass.

### v1.0.0 recovery-safety gate

- [x] Preflight for `.bu` restore built and unit tested.
- [x] Restore results modal with per-item statuses retained.
- [x] Interrupted restore journal and next-start warning built and unit tested.
- [x] Backup and restore staging space checks; atomic backup write kept.
- [ ] Verify new preflight popup and recovery flow in a live Bazzite KDE GUI.
- [ ] Validate cross-distribution and cross-desktop behavior in VMs.
- [ ] Review Flatpak permissions; clean install, icons, translations and final release bundle.

### Update all pre-release checks

- [x] The full update inventory feeds Update all; filter/selection do not affect planned updates.
- [x] One confirmation with No as default, sequential queue, AppImage replacement prompt, failure-stop logic and summary have static/unit coverage (209 tests).
- [ ] On Bazzite, verify Update all enabled with three Flatpak updates and no row selected.
- [ ] On Bazzite, choose No once and verify zero changes.
- [ ] On Bazzite, confirm a multi-app update and check each application's state and refreshed update results.
- [ ] On VM, verify the queue stops on manager errors and handles AppImage skips.
