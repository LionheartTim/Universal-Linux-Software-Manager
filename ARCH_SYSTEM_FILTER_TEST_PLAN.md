# Arch GNOME system-package filter — test build

Based on `Universal-Linux-Software-Manager-v1.0.0-Flatpak-RPM-Inventory-Fix-test.zip` (24 October 2026, 12:44 Amsterdam).

## Change

* The **Arch tab only** now shows verified graphical packages: packages explicitly installed according to `pacman -Qqe` **and** owning a host `/usr/share/applications/*.desktop` launcher according to `pacman -Qqo`.
* Base OS packages, libraries, developer tools and dependencies with no desktop launcher are hidden. Protected system packages are hidden even if they own a launcher.
* If the package ownership or explicit installation reason cannot be verified, the list remains empty and displays a warning rather than exposing all packages.
* Arch removal preflight re-checks eligibility and retains the existing `pacman -R --print` check. No automatic uninstall or mutation is added.
* The **Installation: SYSTEM** indicator remains correct: native pacman packages are stored system-wide, even if installed on user request.
* No changes to the Flatpak, AppImage, RPM, DEB, Snap, Updates, Discover or Backup / Restore logic.

## Real Arch GNOME check

1. On Bazzite, extract this ZIP to a separate project folder and run `bash scripts/build-bundle.sh UniversalLinuxSoftwareManager-v1.0.0-Arch-Filter-test.flatpak` in that folder. The script runs unit tests and creates a test bundle; it does not ship a compiled Flatpak.
2. Transfer the `.flatpak` to Arch GNOME using the working SPICE Remote Viewer drag-and-drop method.
3. Install the bundle in the same Flatpak scope used by the existing installation. Launch Universal Linux Software Manager and click **Arch**.
4. Verify that entries such as `filesystem`, `file`, `fftw`, `fontconfig`, `glibc`, `linux`, `pacman` and `systemd` no longer appear.
5. An explicitly installed graphical application such as Firefox or VLC (if installed as a native pacman package) should still appear.
6. Test search, selection, and rendering only. Avoid removing packages during the first check.

**Limit:** Arch/pacman has no reliable generic distinction between a desktop's default graphical apps and later user-installed graphical apps. This uses explicit reason + desktop-launcher ownership as a conservative heuristic. Some default GNOME apps can therefore remain visible. GUI filtering is not a complete safety guarantee; native dependency checks are still mandatory before removal.

Local regression suite: `python3 -m unittest discover -s tests` (230 passing in the build environment). Actual Arch GUI behavior has not been verified here.
