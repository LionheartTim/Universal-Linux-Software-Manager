# Flatpak + RPM inventory regression (v1.0.0 test)

Fixed Bazzite regressions observed 2026-10-24:

- Flatpak now obtains `name`, `application`, `version`, `arch`, `branch`, and `installation` explicitly from the host. The UI builds an exact `app/ID/ARCH/BRANCH` identity for branch-scoped deletion instead of trusting the display-form `ref` column. If a listing is malformed, deletion still fails closed.
- Flatpak exact-branch removal and post-removal verification both use the same explicit component query. Other branches are untouched; existing user data remains preserved by default.
- rpm-ostree rows must be **both** explicitly layered and own a system desktop launcher. Layered developer packages, tools, libraries and daemons are not displayed or deleted. No base RPM inventory is exposed.

Bazzite practical test:
1. Open Flatpak; installed applications should be listed. Search `qt` and ensure existing PyQt 6.10 and 6.11 versions appear if installed.
2. Attempt to remove ONLY the obsolete 6.10 branch using 'Remove app; keep data'. Confirm that 6.11 is still listed. If host Flatpak refuses, copy exact error, do not force deletion.
3. Open RPM; layered non-GUI packages such as `binutils`, `hidapi-devel` or `dnsmasq` should **not** show. A separately layered graphical package with a `.desktop` launcher should appear.
4. Verify Updates → Update all, Discover, and Backup / Restore still open and function.

Automated tests are host-free: real GUI behavior needs Bazzite validation.
