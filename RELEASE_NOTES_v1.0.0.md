# Universal Linux Software Manager — Release Notes v1.0.0

**Status:** Completed v1.0.0 baseline. Future changes are expected to address confirmed defects or user feedback.

Universal Linux Software Manager combines supported package management, updates, discovery and local backup/restore into a ten-tab PyQt6 application.

## The ten tabs

1. **Flatpak** — Install local Flatpak bundles/references, list applications and safely uninstall the selected installation.
2. **AppImage** — Manage selected local AppImages and manager-owned launchers.
3. **RPM** — DNF, Zypper and rpm-ostree routes where supported, with protected system-package filtering and guarded removal.
4. **DEB** — Local DEB installation and guarded APT removal on compatible systems.
5. **Arch** — Install supported pacman package archives and guard removal of system packages.
6. **Snap** — Signed local Snap installation, or an explicit security warning before a requested unsigned installation, where snapd is available.
7. **Updates** — Source-aware installed-app inventory and **Update all** with confirmation, sequential processing and safeguards against unsupported update routes.
8. **Discover** — **Read-only** search and history for local sources, public GitHub projects and Flathub. Open supported upstream pages and copy available Flatpak identifiers; no installations or downloads from Discover.
9. **Backup / Restore** — Local, checksummed `.bu` archives containing manually supplied installer files and selected supported desktop settings.
10. **Info** — Full **English offline help** in a classic desktop-help layout, with a clickable contents tree, Home / Back / Forward, search (**Ctrl+F**), and context-sensitive **F1** help for the active tab.

## Backup/Restore improvements

- Backup archives store actual selected local installer **files**, not an automatically exported list of installed applications. Backups are **unencrypted**, local ZIP-based `.bu` files.
- Supports selected desktop settings for available adapters, including display, panels, appearance, power, audio, keyboard, notifications, region and file associations.
- Restore checks archive integrity and host compatibility, requests appropriate approvals, and reports succeeded, skipped and failed operations; package restore uses the corresponding package installer.
- **KDE Plasma Next Login Restore:** For KDE sessions using supported Wayland/X11 KWin systemd user units, selected settings are applied via a one-shot user service **before KWin starts at the next login**. Audio is restored separately after login when the audio server is ready. No automatic reboot and no claim of success for unsupported startup modes.
- The KDE workflow is **distribution-independent in code** rather than restricted to openSUSE. It has been practically confirmed on an **openSUSE Leap 16.0 Plasma VM**; not every KDE distribution or older Plasma variant has been physically tested.
- GNOME/Xfce and other available desktop adapters retain their separate workflows.

## Safety and usability

- Filters known system/core packages from package-management lists and guards package deletion with host-specific checks.
- Retains installation-scope visibility (**USER / SYSTEM**) where available, application icons, progress reporting and confirmation dialogs.
- Handles source-matched updates, avoiding silent package-format changes or unsafe individual Arch system upgrades.
- Provides explanatory messages for operations that require authorization or a reboot. GUI installation of a local Flatpak through KDE Discover may show **multiple OS-level password dialogs**; this is documented in `README.md` and `HOW_TO_INSTALL.md`.
- A downloaded `.flatpak` application bundle normally requires a **separate KDE Platform runtime**; Flatpak must already be installed.

## Installation and documentation

- **App ID:** `io.github.LionheartTim.UniversalLinuxSoftwareManager`
- **Repository:** https://github.com/LionheartTim/Universal-Linux-Software-Manager
- **Build command:** `bash scripts/build-bundle.sh UniversalLinuxSoftwareManager-v1.0.0.flatpak`
- **User installation:** See [HOW_TO_INSTALL.md](HOW_TO_INSTALL.md).
- **Detailed behavior and limitations:** See [README.md](README.md) or open the application's **Info** tab with **F1**.
- **Feedback:** https://github.com/LionheartTim/Universal-Linux-Software-Manager/discussions/1

## Compatibility notes

The six package-installation tabs require matching package managers on the host and may use privileged actions. Not every Linux distribution supports every backend, and backup archives are not universal installers or full system images. Flatpak bundles do not embed the KDE runtime. Test on your own distribution before using native removal or large changes on an important machine.

This release completes the planned v1.0.0 feature set; future maintenance can be based on user reports and confirmed issues.
