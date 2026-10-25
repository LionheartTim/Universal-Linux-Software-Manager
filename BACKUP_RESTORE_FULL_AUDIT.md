# Backup/Restore full review — v1.0.0 test build (2026-10-24)

This review covers **both parts** of the `.bu` local backup (embedded installers and desktop preferences) and **all nine** tabs' new Refresh behavior. It is not a claim that every desktop and every native distro has been physically tested.

## Confirmed by earlier hands-on user tests

- Arch GNOME: the user's screen resolution and other tested desktop settings were restored after reboot.
- Xubuntu Xfce: display resolution restored after reboot; **live audio did not** in the previous build.
- Xubuntu: the user installed and removed a Snap; updates were found. A short GUI pause during update loading was reported and deliberately left unchanged.

## This patch: concrete corrections

- **Audio:** backed up from the host session using `pactl` (PulseAudio or PipeWire with `pipewire-pulse`). Saves the selected output and input device names, their master volumes and mute states. Restores only if saved device names exist on the destination host. Stores a `0600` recovery snapshot of the current state. Backup **fails clearly** if host audio state cannot be read: no more false-positive audio backup.
- **Xfce wallpapers:** includes the missing `xfce4-desktop.xml`, alongside existing display, panel, power, look-and-feel, keyboard and notification XML.
- **LXQt appearance:** includes the PCManFM-Qt desktop settings file. No LXQt VM regression test yet.
- **Archive safety:** checksum-verified embedded audio snapshot, strict schema/type/size/device validation. A missing device stops audio application; regular files are checked before writing, and original files/dconf/audio values are kept for recovery. Restore refuses to silently promise live audio from older backups lacking this snapshot.
- **Compatibility:** newly created settings ZIP uses schema 4; schema 2 and 3 settings ZIPs are still readable for the categories they genuinely contain. Old backups cannot be made to include audio retroactively.
- **Refresh:** six installer tabs re-query the host inventory and clear icon caches; Updates forces a recheck; Discover re-runs the current query; Backup/Restore rechecks selected installer files or verifies a loaded `.bu` without clearing it. Controls are disabled while relevant operations are in progress.

## Exact coverage and limitations

| Category | How it is captured | Known limitations |
|---|---|---|
| Local installation files | Only user-selected original installer files | Does not fetch installed packages from the internet or include their dependencies; package installs still require consent. |
| Display | KDE KScreen / GNOME and MATE `monitors.xml` / Xfce displays XML / LXQt session config | Reboot or full desktop login may be needed; SPICE resizing can override a VM resolution. |
| Panel | KDE Plasma applets config / GNOME or Cinnamon/MATE dconf / Xfce panel XML and files / LXQt panel config | Extensions and external themes are **not** guaranteed to be included. |
| Appearance / desktop | Per-DE allowlisted settings; GNOME dconf | Wallpaper image files stored outside these configuration paths are **not** backed up, only their settings/path. |
| Power | DE settings paths or dconf | Hardware-specific features may not be applicable on other systems. |
| Audio | Host `pactl` plus allowlisted configuration files | Only default devices and their volume/mute; no sound-stream, balance, effects or per-application volumes; requires compatible audio devices and working host `pactl`. |
| Keyboard/notifications/region | Only selected allowlisted settings per DE | Unavailable categories remain disabled; some system-level locale defaults are not user-writable. |
| Default apps and file associations | XDG `mimeapps.list` files | Flatpak portal associations may require logging out/in. |
| Flatpak app preferences | Supported by backend for explicitly backed-up Flatpak IDs | Current two-button GUI is intentionally file-oriented; it does not automatically include all installed Flatpak app settings. |

**Safety:** `.bu` archives are not encrypted. They can contain personal desktop settings and executable package files. Keep them in a private location and only install packages you trust. No restore starts without the interactive preflight and per-item approval. No automatic reboot is performed.

## Recommended Xubuntu Xfce verification

1. Open the current test build and confirm each tab has **Refresh**. Install a small app (for example Brave), return to the relevant package tab and press Refresh. Verify the app appears without restarting Universal Linux Software Manager. Repeat in Updates.
2. Change the **audio output volume and mute state** using Xfce's volume control. In Backup/Restore select **Audio settings** and create a *new* `.bu` file. If you get a `pactl` error, do not regard the audio backup as successful; inspect the audio server tools on the VM.
3. Alter the audio volume/mute again. Restore the new `.bu`, approve the settings restore, and inspect the volume/mute afterwards. If the VM offers more than one audio device, also test switching to the backed-up default.
4. In a separate full-settings backup select Display, Panels, Power, Audio, Appearance, Keyboard and any other enabled categories. Change a test setting in each group, restore the `.bu`, then reboot Xubuntu. Confirm which individual settings actually returned; do not assume that one working category verifies all others.
5. Repeat on a newly created user account **only if you intend to test cross-account migration**. Cross-desktop configuration restoration (e.g. KDE → Xfce) is deliberately blocked.

## Testing status

Automated regression tests include missing audio tools, corrupt archive checksums, missing audio devices, inactive operations, previous backup schemas, Xfce file allowlists and nine-tab Refresh wiring. These are **not** a substitute for the real Xubuntu VM test. Other desktops and sound servers may need additional adapters.
