# Backup / Restore: safety preflight and interruption tests (v1.0.0)

## What changed

The **first** Restore backup click opens and checks a `.bu` file in a background worker. The resulting **preflight popup** appears before the second Restore backup click. It shows host and source distro families, CPU architecture, desktop environment, free disk space and an approximate staging footprint. Unsupported entries are marked *Unavailable* in the table before any installation. A cross-desktop settings restore is blocked for safety. This check does not promise that dependencies will be available, or that a package's post-install scripts are harmless.

The **second** Restore backup click starts the familiar sequential approval flow. Individual packages still require explicit consent. The app asks independently before restoring desktop settings. Installation status becomes *Installed* only after the existing package-install job reports success. A no-started-installer condition is an error, not a success or skip.

When the queue completes, a modal dialog reports Installed, Reboot required, Skipped/Cancelled, Failed/Unavailable and Not processed, with per-file outcomes under Details. The list resets **after** the dialog is acknowledged. The `.bu` file is never removed.

A small private JSON restore-state journal under `~/.local/state/universal-linux-software-manager/restore-state.json` records per-file status changes atomically. If an app crashes or power is lost during restore, the next launch **warns** that the prior restore was not confirmed complete and shows last known statuses. It **never automatically reruns** an installer. A newer restore preserves the unfinished journal under a timestamped `interrupted-*.json` file. This is bookkeeping, not a rollback mechanism; actual system package installs can remain partially applied after a crash.

Backup creation checks destination free space **before** writing. The existing `local_file_backup.create_backup` already creates a temporary `.partial` file and atomically replaces the finished `.bu` only after successfully writing it. A failure displays a popup and leaves the previous `.bu` and selected files intact.

## Suggested non-destructive Bazzite checks

1. Open a previously created `.bu`, click **Restore backup** once and review the safety pop-up. Confirm it makes no system changes and shows the correct Bazzite/KDE environment.
2. Check that listed AppImages show *Waiting for approval* and unsupported formats are *Unavailable* if the package manager is missing.
3. Click **Restore backup** again; answer **No** for an unimportant installer. Verify *Skipped*, the end-of-run report, and clean reset after **OK**.
4. For a backup containing settings, review the separate settings confirmation before using it on another desktop/VM.
5. Verify error behavior only using test archives and the automated tests. **Do not intentionally fill a production filesystem, cut power during package writes, or force-kill the system package manager.**

## Automated tests

Run `python -m unittest discover -s tests -q`. Tests include mocked disk-full failures, atomic backup/journal preservation, blocked cross-distro native packages, architecture checks, blocked cross-desktop settings, and uncompleted restore detection. These tests do not replace real GUI and cross-distribution VM testing.
