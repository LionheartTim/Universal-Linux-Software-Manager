# GNOME Backup / Restore – Arch GNOME VM test (2026-10-24)

This is a **test build**, not a confirmed live fix. The `Backup / Restore` tab handles local `.bu` files only. Test with disposable, non-sensitive settings in your Arch GNOME VM. Do **not** delete an original backup during testing.

## What the fix changes

- Detects failures from `dconf dump` on the **host user session** rather than falsely reporting an empty GNOME backup as successful.
- Saves explicitly selected GNOME customizations for the Shell, appearance, background preference, titlebar/window layout, Mutter display/window preferences, power, keyboard, sound, notifications, and region. The existing `~/.config/monitors.xml` file remains the display-profile file.
- Reports categories with no custom values. A GNOME settings-only backup that contains **nothing** now fails visibly instead of producing an apparently successful empty backup.
- Before applying dconf values during restore, saves the current overrides in `~/.local/share/UniversalLinuxSoftwareManager/restore-history/<timestamp>/dconf-before-restore/`, with the prefix manifest (`paths.json`). Existing file-based restore snapshots are also retained there.
- Preserves actionable error messages from a failed host `dconf load` command. If an earlier category was applied before a later one failed, **manual intervention may still be needed**; do not treat the backup as an automatic full rollback.
- Shows a standard reboot reminder after successful backup restoration on **all distributions and desktop environments**; the application does not restart the computer automatically. GNOME Shell and display settings may not visually refresh until reboot.

## Safe, useful live test

1. In **Arch GNOME** (not Bazzite KDE), set GNOME Appearance to **Dark**. Optionally change the order of favorites on the GNOME Dash; this is only a test of visible shell preferences.
2. Open the updated Universal Linux Software Manager > **Backup / Restore**. Check **Appearance / windows**, and if used, **Taskbar / panels**. No installer needs to be added. Click **Create backup** to save `gnome-test.bu` in a writable directory in Arch.
3. The success dialog should report the number of saved **dconf groups** and categories with no customized values. If it says `dconf dump failed`, capture the complete message: the host GNOME session must have a working `dconf` command and session bus.
4. Switch Appearance to **Light** (and rearrange the Dash favorites if used).
5. Click **Restore backup** to open `gnome-test.bu`, review the preflight, then click **Restore backup** again. Accept the **separate settings confirmation**. The status must become `Restored` or `Failed` with a clear error, **never success after a failure**.
6. Reboot Arch GNOME, then check whether Dark mode and the saved Dash preferences are restored.
7. If needed, inspect the archive without extracting untrusted files. In GNOME Files, rename a *copy* of `.bu` to `.zip`, then open it in Archive Manager. Inside `settings.zip`, `manifest.json` should say `"desktop": "gnome"` and `dconf` should contain at least one entry for the relevant category.

## Compatibility and limitations

- **KDE/Plasma → GNOME conversion is not supported**. A `.bu` made on Bazzite KDE cannot recreate Plasma desktop settings inside Arch GNOME. Desktop-family mismatch intentionally blocks restoration of DE-specific settings; installer files remain separately usable when compatible.
- The backup stores **customized dconf values**, not every GNOME default, and `dconf load` merges them. It does **not** reset settings missing from the backup.
- Wallpaper preference URIs can refer to personal image files **not contained in the backup**. These files must already exist at the referenced path on the target machine; extensions and themes themselves also need separate installation.
- Display settings (including `monitors.xml`) may be hardware- and session-specific. Test on the same VM first; avoid using display restore when moving to different monitor hardware.
- GNOME Shell and extension versions can be incompatible across releases. No arbitrary directory or shell script is restored.
- Existing older `.bu` archives with valid saved settings can still be read. A pre-fix archive that silently omitted `dconf` data cannot recover those missing settings; create a **new backup in GNOME**.
