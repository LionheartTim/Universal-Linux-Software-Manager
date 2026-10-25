# DEB / Snap graphical-app filtering + universal reboot notice

Test build based on the previously validated GNOME Backup/Restore Fix.

## 1. DEB (Ubuntu or Debian VM)

1. Open the DEB tab and click Refresh. Verify the OS plumbing (e.g. `base-files`, `libc6`, `dpkg`, `apt`, `systemd` and ordinary libraries) is **not** offered as removable software.
2. Verify an explicitly installed graphical `.deb` application with a package-owned launcher remains visible. APT's manual status is necessary but not sufficient for display. A distro-bundled graphical app might still appear.
3. Optional *read-only* comparison in a VM terminal: `apt-mark showmanual` and `dpkg-query -S /usr/share/applications/<app>.desktop`.
4. No need to actually remove any packages. The regression tests check the APT simulation and the package-ownership gate.

## 2. Snap (Ubuntu VM with snapd and graphical snaps)

1. Refresh the Snap tab. `core*`, `bare`, GNOME/Mesa content runtimes, `snapd` and common integration snaps should be absent.
2. Apps such as Firefox/VLC are shown only if their launcher appears under `/var/lib/snapd/desktop/applications/`.
3. If the GUI launcher directory cannot be queried, no entire Snap inventory should be exposed.
4. Don't test by removing system snaps; the remove handler rechecks the app marker and current installation.

## 3. Restore + reboot message (any distro / desktop)

1. Back up a small reversible desktop preference on a disposable test VM.
2. Change it, then restore the backup with the normal approvals.
3. After a successful restore the summary must display the prominent **REBOOT YOUR COMPUTER / HERSTART JE COMPUTER** message. The message must not be GNOME-specific.
4. No automatic restart should occur. Reboot manually and check the restored preference.
5. On a fully failed/skipped restore the summary must not pretend that settings were successfully applied.

## Constraints

The DEB/Snap filters are deliberately conservative and may hide legitimate GUI apps.
APT manual-install state is not proof of a user choice when creating the OS image.
Automated tests are not a substitute for Debian/Ubuntu/Snap runtime checks.
