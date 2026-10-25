# Backup / Restore — v1.0.0 local testing

## Intent
Only back up chosen installed applications and compatible user settings. Never imply that *every* distribution exposes an authoritative list of its factory/preinstalled applications.

## Changes
- Clear, grouped interface: **1. Choose backup contents** / **2. Create backup** / **3. Restore backup**.
- App list hides confidently detected core packages and automatic dependencies (APT / Pacman); other kinds use the installed inventory. Reversible **Mark as distro app** preferences let users hide preinstalled Flatpaks/Snaps/other defaults which Linux cannot reliably identify. These markings are stored locally in `~/.local/share/UniversalLinuxSoftwareManager/backup-exclusions.json`, and **never remove packages**.
- **Show also distro apps / dependencies** displays hidden rows for review; hidden items remain unchecked even if shown. Native packages of uncertain origin are visible but unchecked. Explicit selections are required.
- **Select all / Select none**, **Refresh list**, **Create local ZIP backup**, **Open existing backup**, and two distinct **Restore** buttons. Restore actions are disabled until a backup is opened.
- Optional categories: **Keyboard / shortcuts**, **Notifications**, **Language / region (user)**, **Default apps / file types**; only if a compatible desktop adapter exists, with file associations portable where possible. Never restore desktop-specific paths onto an incompatible desktop.
- **Flatpak settings (config only)** exports `~/.var/app/<app-id>/config` for checked Flatpak apps only. Does NOT export `data`, `cache`, Flatpak permissions/overrides, or entire account profiles unless those apps happen to store them under config.
- Flatpak sandbox now explicitly requests `--filesystem=~/.var/app` because `--filesystem=home` alone does **not** grant access to other applications' per-app config. This permission is broad; this option remains off by default and a local non-encryption warning remains in place.
- Backup schema 3; existing schema 2 archives stay readable. Source target compatibility and integrity validation still enforced.

## Bazzite test sequence
1. Build and start (not bundle). Open **Backup / Restore**.
2. Confirm KDE detected. Refresh installed list. Check base packages hidden, and mark a known default Flatpak as preinstalled; ensure it disappears. Check **Show also distro apps / dependencies**, select it, and **Unmark distro app**; verify it appears again after Refresh.
3. Tick only **Installed applications** and choose 1–2 harmless extra applications. Create ZIP. Open ZIP, verify chosen apps are listed.
4. Tick **Keyboard / shortcuts** and **Notifications** with a harmless desktop setting, make backup and inspect ZIP. Restore only after ensuring a separate KDE recovery point and compatible desktop version. Log out and back in to verify changes; Plasma may rewrite settings on session exit.
5. Test **Flatpak settings (config only)** separately with a non-sensitive test app and *inspect the ZIP before restore*. It may contain account tokens; never upload or share it unencrypted.
6. Verify no existing app, system file, or setting is removed by marking an app as excluded.

The new UI and host-specific probes cannot be confirmed from CI/unit tests. Test on Bazzite first, then on other distros/desktops. This is a development preview, NOT a release bundle.
