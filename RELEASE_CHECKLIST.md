# Universal Linux Install & Uninstall Center — Release checklist (v1.1.0)

## Before release

- [ ] Review manifest host access (`--talk-name=org.freedesktop.Flatpak`) and filesystem permissions.
- [ ] Run `python3 -m unittest discover -s tests -v`.
- [ ] Run `python3 -m py_compile main.py`.
- [ ] Run `desktop-file-validate` and `appstreamcli validate --explain` where available.
- [ ] Build Flatpak using `bash scripts/build-bundle.sh` (requires Flatpak Builder and access to Flathub dependencies).
- [ ] Install and launch bundle on a clean test user or virtual machine.
- [ ] Check launcher, window icon, taskbar icon, 6 tabs, 16-block progress indicator and USER/SYSTEM/Status columns.
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
