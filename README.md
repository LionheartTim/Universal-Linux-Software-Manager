# Universal Linux Software Manager

**Version 1.0.0** · Linux desktop software management · Python / PyQt6

Universal Linux Software Manager brings supported Linux application installers, updates, software discovery, and local backup/restore tools together in one graphical interface. The application has **ten tabs**:

**Flatpak · AppImage · RPM · DEB · Arch · Snap · Updates · Discover · Backup / Restore · Info**

The Info tab includes a complete **offline English-language help guide**. Press **F1** to open the chapter for the current tab; use the contents tree, **Home / Back / Forward**, or **Ctrl+F** to search.

> **Platform scope:** This is not a replacement for every Linux distribution's system package manager. Features depend on the host distribution, available tools, permissions, and package format. Protected or unsupported operations are intentionally unavailable.

## Install the application

Download the `.flatpak` application bundle from the project's release page and open it with your distribution's Flatpak-enabled software center. On KDE Plasma this is typically **Dolphin → double-click the bundle → Discover → Install**. A network connection may be needed to download the separate KDE Platform runtime.

**Why might the installer ask for your password more than once?** Your software center and the operating system handle authorization *before Universal Linux Software Manager starts*. For a system-wide installation, KDE Discover / PolicyKit may request administrator authorization during more than one installation step, such as installing the application or required runtimes. The number of prompts depends on the distribution, software center, cached authorization, and installed dependencies; three prompts were observed during openSUSE testing. These prompts are not requested by this application's Python code. Check that the dialog comes from your trusted system installer and that you opened the expected file before entering a password. Do not disable system authentication to suppress prompts.

Alternatively, a per-user installation can often avoid administrator authentication:

```bash
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user --bundle "/path/to/UniversalLinuxSoftwareManager-v1.0.0.flatpak"
flatpak run io.github.LionheartTim.UniversalLinuxSoftwareManager
```

Replace the example path with the downloaded bundle's actual location. The app is not assumed to be published on Flathub merely because its *runtime* may be downloaded from Flathub. Flatpak must be installed first; some distributions do not provide it by default. See **[HOW_TO_INSTALL.md](HOW_TO_INSTALL.md)** for graphical/terminal installation and distribution-specific setup.

## Supported package tabs

| Tab | Purpose | Important limitations |
|---|---|---|
| **Flatpak** | Install supported local `.flatpak` bundles or `.flatpakref` references; list and remove installed applications | Handles USER/SYSTEM scope and exact installed refs. Runtimes may require a configured remote. |
| **AppImage** | Add local AppImages to `~/Applications`; manage launchers and removal | Only manager-owned launchers/files are removed automatically; user preferences are retained. |
| **RPM** | Install and safely remove eligible packages on compatible RPM-based hosts | `rpm-ostree` can require reboot; DNF/Zypper removal is guarded by package and dependency checks. Core/system components, including known Plasma packages, are excluded. |
| **DEB** | Install local `.deb` files and remove eligible apps on Debian/Ubuntu-style systems | APT dependency checks block unsafe removal of essential packages. |
| **Arch** | Install local pacman package archives and remove eligible apps | Protects core/system packages; does not perform risky individual Arch system upgrades. |
| **Snap** | Install/remove local Snaps where `snapd` is available | Signed local `.snap` + `.assert` is preferred. Unsigned files require an explicit warning and confirmation of `--dangerous`. |

The package lists focus on recognizable user applications, not every installed dependency. On DNF/Zypper, launcher ownership and protective filtering can hide some legitimate command-line tools. Installation/removal remains subject to the host package manager, its dependency solver, and PolicyKit authorization. A preview does not guarantee that a later transaction cannot differ if the system changes in between.

## Updates

- Refresh the inventory of installed applications from supported package managers, showing source, status, and available updates where discoverable.
- **Update all** reviews eligible updates across the supported installed inventory, not just the currently filtered rows. Updates are handled sequentially, with confirmation.
- Preserve the **original installation source**: a Flathub app is not silently replaced by a GitHub release or another package format.
- Tracked GitHub AppImages can be updated using verified/staged download and a separate confirmation before replacement. Untracked AppImages are not silently attributed to GitHub repositories.
- Arch full system upgrades and Fedora Atomic / Bazzite OS deployments remain the responsibility of their native system updater. Unsupported update routes report their limitations instead of attempting unsafe partial upgrades.

## Discover — read-only

Discover searches available local package sources and, when connected, public Flathub/GitHub data. Depending on the source, it can display upstream release history, Flatpak build/commit information, official pages, and copyable identifiers.

**Discover does not download, install, uninstall, upgrade, downgrade or switch application sources.** Any user-approved installation is performed separately in the appropriate package tab or externally. Public search results do not verify publisher identity; check upstream project links yourself.

## Backup / Restore — local `.bu` files

Backups are **local and unencrypted**. The `.bu` container is a ZIP-based archive; it can contain:

- Actual **local installer files** added manually or by drag and drop: `.flatpak`, `.AppImage`, `.rpm`, `.deb`, Arch package archives and `.snap`. It does **not** automatically extract executables from installed applications.
- Supported **desktop settings**, where present and accessible: display, panels, appearance, power, audio, keyboard, notifications, locale and file associations.
- Checksums and metadata for validation before restoring. Application installers are restored through their compatible package-tab workflow and any required confirmation.

**Create Backup** saves the selected contents. **Restore Backup** loads the archive for inspection and compatibility checks; follow the on-screen instructions and explicit approvals to begin restoration. Backups can include sensitive personal desktop preferences or installers; store them securely. They are not complete system images, application-data backups, or universal installers for incompatible distributions.

### KDE Plasma — restore at the next login

KWin/Plasma may overwrite configuration files written while a desktop session is still running. For supported KDE Plasma installations, Universal Linux Software Manager therefore **stages selected settings for the next login** instead of claiming they were fully restored immediately:

1. Verify the selected KDE backup and stage a one-time **systemd user service**, ordered to apply saved configuration files before the corresponding KWin startup service.
2. Show that a **restart is required**; the app never restarts the computer automatically. Restart and sign in to the same supported KDE session type.
3. Restore audio separately after login when the audio server is available, and report failures independently from other settings.

This route supports detectable Plasma **Wayland or X11** systemd KWin user services and available legacy KScreen / Plasma 6 KWin display configurations. It is not tied to openSUSE: the same detection and safety checks apply on other distributions. For customized or older Plasma sessions without the necessary startup units, the app should **decline to schedule** deferred restore instead of making an unsafe promise. Other desktops retain their own restore adapters; KDE service staging does not replace the GNOME or Xfce restore workflow.

**Verification:** The next-login workflow was confirmed in an openSUSE Leap 16.0 Plasma VM. Automated cross-distro checks also cover other KDE environments, but that is **not** proof of physical testing on every distro, Plasma version or session. Verify the actual screen, panels, audio and desktop settings after login; file checksums alone cannot establish that the desktop applied every preference.

A reboot may also be recommended after settings restore on other desktop environments. See the **Info → Backup / Restore** and **Info → Troubleshooting** chapters for guidance.

## Security and practical limitations

- System package operations may require PolicyKit / `pkexec`. Review every authorization dialog and transaction plan.
- The Flatpak uses host integration for native package managers. Its sandbox permissions are broader than those of a simple sandboxed reader; install only from a trusted source.
- Unsafe package removal is blocked where recognized. No application can guarantee protection against every package-manager configuration or third-party script.
- `Update all` respects known source associations and does not silently cross formats.
- `.bu` archives are **not encrypted**. No cloud account or automatic upload is part of the backup workflow.
- The app includes desktop adapters for KDE Plasma, GNOME, Xfce and other supported environments where a settings source is available. Not every setting exists or can be reliably restored on every desktop.
- Native package formats are often architecture- and distribution-specific. Local Flatpak bundles also generally require a separately installed compatible runtime.

## Build from source

Prerequisites: **Flatpak**, **flatpak-builder**, a configured **Flathub** remote, and build access to **org.kde.Sdk//6.11**, **org.kde.Platform//6.11**, and **com.riverbankcomputing.PyQt.BaseApp//6.11**.

From the unpacked source directory:

```bash
bash scripts/build-bundle.sh UniversalLinuxSoftwareManager-v1.0.0.flatpak
```

The build script performs project checks and creates an application bundle when its build dependencies are present. The bundle does not include the separate KDE runtime. Build separately for each CPU architecture to be distributed.

If you encounter installation or build problems, read **[HOW_TO_INSTALL.md](HOW_TO_INSTALL.md)**, the application's **Info / F1 Help**, and the available test plans in the source package.

## Project and feedback

- **Application ID:** `io.github.LionheartTim.UniversalLinuxSoftwareManager`
- **Source repository:** https://github.com/LionheartTim/Universal-Linux-Software-Manager
- **User-facing release notes:** [RELEASE_NOTES_v1.0.0.md](RELEASE_NOTES_v1.0.0.md)
- **Feedback and bug reports:** https://github.com/LionheartTim/Universal-Linux-Software-Manager/discussions/1
- **License:** GPL-3.0-only (see `LICENSE`)

Version **1.0.0** is the completed project baseline. Further functional changes are intended to be driven by confirmed defects or user feedback, not untested additions.
