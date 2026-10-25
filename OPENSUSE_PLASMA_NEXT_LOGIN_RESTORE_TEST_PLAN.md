# openSUSE Plasma 6 — deferred Backup/Restore VM test

This is a **test build**. No automatic reboot. The previously working GNOME/Xfce paths are unchanged. Do **not** assume successful integration merely because unit tests pass.

## Why a deferred restore?

A running KDE Plasma/KWin session can overwrite configuration files during shutdown. This revision schedules **one-time, user-level** services instead of writing KDE settings immediately: the file phase is ordered before `plasma-kwin_wayland.service` (or X11 equivalent) and the separate audio systemd service is activated asynchronously by KDE XDG autostart after login, waiting for `pactl` to become available. It cannot hold up the KWin startup.

The host must support **systemd-managed Plasma startup**. If that KWin unit is not loaded, the app refuses to schedule rather than falsely reporting a successful restore. No root privileges or system-wide services are installed. It uses the existing Flatpak permission to run limited host-side `systemctl --user` commands.

## Test once in the openSUSE VM

1. Keep the known-good `.bu` file safe and note the current resolution, selected speaker, volume, wallpaper, panel arrangement, power, keyboard and other customized settings.
2. Open the **new** Flatpak build and use **Backup / Restore → Restore backup** twice (preflight then approval).
3. Expected row status: **Reboot required**. Before reboot, the current configuration should remain unchanged. If you see **Failed**, read the error message; do not assume it is scheduled.
4. On the host terminal inside the openSUSE VM, you may check scheduling:

   ```sh
   systemctl --user is-enabled ulsm-plasma-settings-restore.service
   test -f "$HOME/.config/autostart/ulsm-plasma-audio-restore.desktop" && echo "Audio queued for next login"
   ```

   The audio autostart is expected only if the backup contains a live audio snapshot. It starts a separate one-shot systemd unit without blocking Plasma.
5. **Reboot the VM yourself**, then sign in to the same KDE Wayland/X11 session as before.
6. Recheck actual resolution, panels, desktop theme, power and other selected settings. Check live audio device, mute and volume separately.
7. To inspect the one-time result without changing anything:

   ```sh
   cat "$HOME/.local/share/UniversalLinuxSoftwareManager/deferred-plasma/status.json"
   systemctl --user --no-pager status ulsm-plasma-settings-restore.service
   systemctl --user --no-pager status ulsm-plasma-audio-restore.service
   ```

   Status `files=applied` means files were **written and immediately checksum-verified before KWin**. It does **not** prove Plasma kept every setting after startup. If the resolution/panel is still wrong, compare hashes against the `.bu` after login.
   Status `audio=applied` means the saved live audio state was applied and verified by pactl. `failed` records a specific error; it will not silently report success.

## Safety and recovery

- Each existing destination is copied to `~/.local/share/UniversalLinuxSoftwareManager/restore-history/before-deferred-...` before overwrite. The original `.bu` file is not deleted.
- Restore is attempted once; successful or failed phases disable their own user service. When a unit cannot be found, the app refuses to schedule it.
- If the selected monitor configuration is unsuitable and display recovery is necessary, use a TTY or VM rescue console. The old KWin config file is in the restore-history location reported in `status.json`. Do not remove the `.bu` file.
- To cancel a staged restore **before reboot** (no desktop files have been changed yet):

  ```sh
  systemctl --user disable ulsm-plasma-settings-restore.service
  rm -- "$HOME/.config/autostart/ulsm-plasma-audio-restore.desktop"
  ```

- The interface reads the saved status when you reopen Backup/Restore, but you must still visually verify actual desktop settings.

The password-prompt explanation in README, F1/Info tab and Discover rating ideas are intentionally **deferred until after VM testing**, as requested.
