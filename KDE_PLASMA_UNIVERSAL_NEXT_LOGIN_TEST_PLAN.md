# KDE Plasma — distro-independent next-login restore (v1.0.0 test)

**Scope:** Extend the *already verified on openSUSE Plasma 6* one-shot restore to KDE Plasma on other Linux distributions. Not a claim that each distribution or KDE release has been physically tested.

## How it works

- **No distribution allowlist.** Whenever the running desktop identifies as KDE/Plasma and the imported backup is also a KDE desktop backup, use the same deferred restore logic on any Linux distribution.
- **Wayland / X11:** Select the corresponding `plasma-kwin_wayland.service` / `plasma-kwin_x11.service`. When the current session type is not exported to the Flatpak, accept exactly one **active** host KWin systemd user service as evidence of which session is running. Never infer from an installed-but-inactive service.
- **Early phase:** Stage approved KDE settings and install an enabled, one-time *user* systemd service ordered before KWin. Restore is verified by file checksums. Old display layouts from `.local/share/kscreen` and new Plasma 6 `.config/kwinoutputconfig.json` are both supported, as present in the archive.
- **Late phase:** A separate one-shot service, triggered asynchronously after KDE login, applies the live audio snapshot once the audio server is available. An audio error must not undo restored desktop files.
- **No automatic reboot, root permissions, system-wide service, or GNOME/Xfce change.** The user initiates a restart and signs in to the **same KDE session type**.
- **Fail safely:** If the running session does not use a detectable systemd KWin unit (older/classic or customized startup), refuse to schedule rather than promise the settings will be applied before Plasma.

## Manual verification matrix (not yet completed)

| Environment | Session | Expected test |
| --- | --- | --- |
| openSUSE Leap 16 Plasma 6 | current Wayland/X11 | Previously verified by user. Re-test only if convenient. |
| Fedora KDE / Bazzite KDE | Wayland | Create, stage, reboot; verify display, panels, power, appearance and audio. |
| Arch Plasma | Wayland or X11 | Test same settings, one-shot behavior and safe staging. |
| Kubuntu / Debian KDE | Wayland or X11 | Test same settings and that user units are really active. |
| KDE Plasma 5 with systemd KWin | supported session | Test older `.local/share/kscreen` format with a safe known-good backup. |
| Older or classic non-systemd KDE session | either | Expect a clear unsupported-startup error and **no** falsely claimed restore. |

For each supported host, check `systemctl --user show --property=LoadState,ActiveState plasma-kwin_wayland.service` and similarly `plasma-kwin_x11.service`. Use **Restore Backup**, confirm **Reboot required**, restart manually and confirm the *actual* settings (not just file hashes). Audio should be checked separately. Review `$HOME/.local/share/UniversalLinuxSoftwareManager/deferred-plasma/status.json` for `files` and `audio` results.

To cancel **before reboot**, run `systemctl --user disable ulsm-plasma-settings-restore.service` and remove only the app-owned audio autostart entry `.config/autostart/ulsm-plasma-audio-restore.desktop` if one was staged.

**Not included yet:** README explanation of repeated password prompts when double-clicking a Flatpak bundle; the Info/F1 Help tab; Discover review/rating changes. Per user request, these remain after VM testing.
