# Flatpak precise branch removal — Bazzite test (v1.0.0)

## Regression: PyQt BaseApp 6.10.2 and 6.11.0

1. In **Flatpak**, search for `qt`. Confirm the USER entries for PyQt BaseApp 6.10.2 and 6.11.0 are both visible.
2. Select **only** 6.10.2. Press **Uninstall selected**.
3. In the first dialog, confirm the **exact** reference contains `/6.10` and the installation reads `user`.
4. Choose **Remove app; keep data** (the default), and allow the operation to finish.
5. Confirm 6.10.2 disappears while 6.11.0 remains.
6. Restart the app or switch tabs, and check that 6.11.0 and existing software still work.
7. If an error or unverified-removal warning appears, collect the app's diagnostic output. Do not use a force removal.

The app uses an exact `app/ID/ARCH/BRANCH` reference. When multiple branches exist, `--delete-data` is not offered, because data is shared by ID. It never adds `--unused` or `--force-remove` and it checks the exact ref again after uninstall. No system-wide cleanup is attempted.

## Optional host-side read-only cross-check

`flatpak list --app --columns=name,application,version,installation,ref | grep PyQt`

This read-only command confirms the actual refs. The exact active branch may differ from the displayed version number.

## Automation

`python -m unittest discover -s tests -q`

A host-side PyQt6 GUI/Flatpak uninstall run has not been executed in this development environment. This build must be tested on Bazzite before declaring the branch-removal issue resolved.
