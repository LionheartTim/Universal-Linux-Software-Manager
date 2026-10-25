# openSUSE Plasma 6 — Complete Backup/Restore audit (test build)

## Scope and evidence

Source baseline: `Universal-Linux-Software-Manager-v1.0.0-openSUSE-RPM-System-Filter-test.zip`.
The review includes the nested settings ZIP and local `.bu` archive integration; KDE Plasma paths; host sound commands; the list of selectable categories; integrity/rollback; and differences between automated tests and an actual openSUSE Wayland session.

### Confirmed by user in openSUSE before this patch

- Display resolution **does not return** after restoring and rebooting.
- Audio setting **does not return** after restoring and rebooting.
- Other desktop categories have **not** been physically tested yet.

### Source-derived issues and adjustments

- **Display:** Old code saved `~/.local/share/kscreen` only. Plasma 6 Wayland may instead use `~/.config/kwinoutputconfig.json`. Both paths are now supported, with no generic write to `/etc` or system settings.
- **Panels:** Plasma applet layout (`plasma-org.kde.plasma.desktop-appletsrc`) and shell preferences (`plasmashellrc`) were already included. The session can overwrite configuration while running; reboot behavior still requires a real VM check.
- **Power:** `powerdevilrc` and `powermanagementprofilesrc` were already supported.
- **Audio:** Snapshot via real host-session `pactl` stores default input/output, volume, mute. The restore now reads back these settings immediately and reports a failure if they differ. Live WirePlumber files under `.local/state/wireplumber` are no longer copied into new backups or applied during restore, because the running daemon owns that state and may overwrite it. Earlier archives remain inspectable.
- **Appearance/windows:** Added `plasmarc`, `kwinrulesrc`, `kscreenlockerrc`, `ksplashrc`, `kcmfonts` and `breezerc` along with existing `kdeglobals`, `kwinrc`, `ksmserverrc`. Custom third-party themes and actual wallpaper image files outside those paths are NOT included; only references/configuration are saved.
- **Keyboard/shortcuts:** `kglobalshortcutsrc`, `kxkbrc`, `kcminputrc` already included.
- **Notifications:** `plasmanotifyrc` supported if it exists; other notification-service configuration not guaranteed.
- **Language/region:** `plasma-localerc` supported. Does not overwrite the system locale or system-wide language packs.
- **Default apps/file types:** User-level XDG `mimeapps.list` paths already included.
- **Installed apps / app settings:** `.bu` holds dragged installer files; Flatpak app config can be restored only if backed up by the supported backend. It is not a whole-system snapshot.

### Safety

- Restoration keeps previous file versions under `~/.local/share/UniversalLinuxSoftwareManager/restore-history`.
- The `.bu` is local and **not encrypted**. Keep it private.
- Desktop-family mismatch still blocked.
- No elevated/system-wide configuration changes and no automatic reboot.
- Old backups cannot gain missing Plasma 6 display settings or newly omitted contents retrospectively. Create a **new** `.bu` using this version before re-testing.
- A successful immediate audio verification does NOT prove persistence after logging out or rebooting. An active KDE/Wayland session can also overwrite saved output and panel configuration at shutdown. Never mark those categories as physically working until a real reboot test confirms it.

## openSUSE Plasma VM manual test plan

1. Run the new bundle on openSUSE Plasma. Before changing settings, confirm whether `~/.config/kwinoutputconfig.json` exists in the user account. If absent, the saved display layout may reside elsewhere and will require diagnosis.
2. Change ONLY an easily reversible screen resolution; choose **Display settings** when creating a **new** `.bu`. Inspect the creation summary: Display must not appear under `No customized values found`.
3. Change resolution to another valid mode; restore the `.bu`; record whether it changes immediately; reboot. If the original mode does not come back, collect the restored file's timestamp and `kscreen-doctor -o`. DO NOT overwrite or delete display files manually.
4. Change output volume (e.g. from 30% to 65%) and, if safe, mute. Include **Audio settings** in a new backup. Change volume again and restore. Confirm the live volume and mute immediately (not just after reboot), then reboot and confirm again. If an error is shown, preserve its exact text.
5. Create a separate full desktop settings backup. Try one reversible change in each group: panel alignment/height, Plasma style, power screen-blank timeout, one temporary keyboard shortcut, notifications behavior, language/region (if practical), and one noncritical default file association. Restore and reboot. Report per group: restored / failed / not tested.
6. Verify the two bold, enlarged messages are visible in the restore workflow: `Click Restore backup again to start` and `IMPORTANT: REBOOT YOUR COMPUTER ...`.
7. If Restore reports success but an individual setting did not return, record the category and the app's completion status; this is a real issue, not proof of successful restore. There is no need to reinstall openSUSE.

## Deferred until after all openSUSE tests

- README explanation of repeated polkit/Discover password dialogs during graphical `.flatpak` installation.
- English F1 Help / Info tab and the read-only Discover ratings addition.

## Reproduction / static verification

`python3 -m unittest discover -s tests -q`
`python3 scripts/check-packaging.py io.github.LionheartTim.UniversalLinuxSoftwareManager.json`

Tests use a temporary home directory and simulated host audio calls. They **do not** exercise openSUSE Plasma, KWin, PipeWire or SPICE in a real desktop session.
