# Universal Linux Install & Uninstall Center

**Version 1.1.0**

Python/PyQt6 application with six tabs: Flatpak, AppImage, RPM, DEB, Arch and Snap. This is **not** a universal replacement for every distro's native software manager. It only enables managers that match the running host and are available there.

## Supported workflows

| Package format | Installation | Removal | Notes |
|---|---|---|---|
| Flatpak | Local `.flatpak` and `.flatpakref` per user | Yes; choose to keep user data or delete it when safe | Other installations preserve shared app data |
| AppImage | `.AppImage` to `~/Applications` with desktop launcher | Managed AppImages only | User files/preferences outside app are retained |
| RPM on Bazzite/Fedora Atomic | `rpm-ostree install` | Explicitly requested package layers only | Reboot required; no base OS package removal |
| RPM on Fedora/DNF | Local `.rpm` through DNF with Polkit | Yes, for verified graphical applications when a single-package RPM dependency test succeeds and the solver preview is reviewed | DNF explicit-install reason required; no automatic dependency cleanup |
| RPM on openSUSE (traditional) | Local `.rpm` via Zypper with Polkit | Yes, for recognized graphical applications after a safe RPM dependency test and Zypper dry-run preview | No ordinary Zypper writes on MicroOS/Aeon |
| DEB on Debian/Ubuntu | Local `.deb` via APT with Polkit | Yes only when dry-run removes selected package alone | Essential packages blocked |
| Arch/Manjaro | Local `.pkg.tar.*` through pacman with Polkit | Yes only explicit packages with single-package plan | Core packages protected by extra deny list |
| Snap (with snapd) | Signed `.snap` plus `.assert`, OR unsigned `.snap` with an explicit dangerous-file confirmation | Yes | An unverified local snap skips signature/assertion verification using `--dangerous` **only after explicit Yes**; not recommended for untrusted sources |

### RPM listing / system protection

A Linux RPM database does **not** contain a universal, reliable “core system” Boolean. Instead, on standard DNF/Zypper systems the RPM tab restricts itself to packages owning an installed graphical `.desktop` application launcher. DNF additionally requires the package to be listed as explicitly/user installed. Critical known OS/desktop packages are excluded by an additional deny list. Consequently **some command-line apps without a desktop launcher will not appear**; application launchers shipped in nonstandard directories may also be missed. This is a deliberately conservative application list, not an exhaustive RPM inventory.

Before RPM deletion, the app rechecks the package, runs `rpm -e --test` (possibly through Polkit if necessary), and previews the DNF or Zypper transaction. Users must accept the displayed plan. DNF uses `--no-autoremove` / disabled automatic dependency cleanup; Zypper uses `--no-clean-deps --no-force-resolution`. Package managers can still perform other changes in unusual configurations: the dry-run and the real transaction can differ if repositories/package states change between steps. Backups and native-system testing are recommended before production use.

### Snap security choice

If no matching `.assert` file exists, the app asks whether to install an unsigned `.snap` anyway, explicitly warning that it might be dangerous or malicious, with **No** selected by default. If approved, Snap's `--dangerous` skips publisher verification. This is not a malware scanner and accepting the warning does not make the file safe. Prefer signed snaps or Snap Store downloads.

### Other distribution families

NixOS uses Nix, Alpine uses apk, Gentoo uses Portage (`emerge`), and Void uses XBPS (`xbps-install`/`xbps-remove`). Their native package operations are **not** currently represented in the six tabs. They may still use supported Flatpaks and AppImages where installed and permitted.

**Warning:** System package managers (APT, pacman, Zypper, DNF) may still fail due to authorization, policy, package conflicts, scripts or dependencies. Do not test destructive operations on essential packages. A successful command is not a universal guarantee that a reboot will never be necessary.

## Flatpak sandbox

Uses `flatpak-spawn --host` for host-side manager operations. Needs appropriate Flatpak sandbox permissions and Polkit authorization for system-wide changes. Only the distribution's actual manager is selected using `/etc/os-release`. Systems outside these supported families may show unavailable tabs, which is deliberate.

## Build prerequisites

* Flatpak + flatpak-builder
* Flathub remote
* `org.kde.Sdk//6.10` and `org.kde.Platform//6.10`
* Build-time `com.riverbankcomputing.PyQt.BaseApp//6.10` (PyQt6 is supplied by the baseapp, no unpinned `pip install`)

The BaseApp is used **at build time**. The end user's application uses its one KDE Platform runtime, not all Linux runtimes. A standalone `.flatpak` bundle does **not** contain its runtime; Flatpak downloads that dependency from a configured remote if needed. Build separately for each desired CPU architecture.

### Local test build

```bash
cd "/home/Tim/Desktop/Flatpak and Appimage Center/"
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak-builder --user --install --install-deps-from=flathub --force-clean build io.github.LionheartTim.UniversalLinuxCenter.json
flatpak run io.github.LionheartTim.UniversalLinuxCenter
```

### Export application bundle (not a full offline runtime bundle)

```bash
flatpak-builder --user --install-deps-from=flathub --force-clean --repo=local-repo build io.github.LionheartTim.UniversalLinuxCenter.json
flatpak build-bundle --runtime-repo=https://dl.flathub.org/repo/flathub.flatpakrepo local-repo UniversalLinuxCenter-v1.1.0.flatpak io.github.LionheartTim.UniversalLinuxCenter
```

You can also run `bash scripts/build-bundle.sh` to build the distributable app bundle with dependency downloads handled for the build.

For a fully offline delivery use Flatpak's `create-usb` workflow with dependencies, instead of assuming a single `.flatpak` bundle contains everything.

## Internal Flatpak identity

App ID: `io.github.LionheartTim.UniversalLinuxCenter`. The updated glossy project icon and KDE desktop entry are retained. The GUI still shows **v1.1.0**, and the animation remains the 16-block seamless blue conveyor.

## Safety and testing status

Python syntax, manifest parsing and static checks can be performed without a Linux desktop. Actual builds and package transactions on Debian, Fedora, openSUSE, Arch and Snap environments **have not been verified here**. Host package manager operations remain sensitive even with preflight checks. Distribution differences can require additional changes.

Official documentation: [Flatpak](https://docs.flatpak.org), [PyQt BaseApp](https://github.com/flathub/com.riverbankcomputing.PyQt.BaseApp), [rpm-ostree](https://coreos.github.io/rpm-ostree/administrator-handbook/), [Zypper](https://manpages.opensuse.org/Tumbleweed/zypper/zypper.8.en.html), [Snap install modes](https://snapcraft.io/docs/explanation/snap-development/install-modes/).


## Feedback & bug reports

Use **Send Feedback** or **Report a Bug** in the app footer. Both open the project discussion:

https://github.com/LionheartTim/Universal-Linux-Install-Uninstall-Center/discussions/1

No diagnostic information is uploaded automatically; the link is opened in the default browser.


## Final release-candidate improvements

* **Safe exit:** Closing the main window while a package job is running is blocked and shows a simple warning. Wait until the job finishes; force-killing the application or desktop session is not guaranteed to cancel package-manager transactions.
* **Atomic AppImages:** AppImages are first copied into a hidden temporary file in `~/Applications`, checked for complete copy and unchanged source, and made executable before publishing the final filename. A launcher is staged separately and incomplete installations are rolled back.
* **Startup compatibility:** Every tab checks host package-manager availability and, where required, Polkit (`pkexec`) and local write locations. Unavailable install/uninstall controls are disabled with an explanation. Availability does not guarantee successful authorization or a safe package-specific transaction.
* **Release files:** `LICENSE` contains the GPL-3.0 license; metadata includes project, support and release links. `scripts/build-bundle.sh` runs static tests, optional local validators and builds the bundle if Flatpak Builder is installed.

**Release status:** Static tests do not replace distro-specific runtime tests. See `RELEASE_CHECKLIST.md` before publishing. Flatpak host-spawn privileges are powerful: review them carefully before distributing this application.
