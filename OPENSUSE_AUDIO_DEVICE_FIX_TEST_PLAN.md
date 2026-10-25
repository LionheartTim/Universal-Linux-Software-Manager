# openSUSE Plasma — changed audio-device restore test

This build addresses the concrete restore error:
`Saved audio sink is unavailable on this computer: alsa_output.pci-0000_00_1b.0.analog-stereo`

## What changed

- Before changing any desktop settings, detect whether each saved audio device still exists.
- If the saved device name changed, use an alternate name only when there is exactly ONE currently available device of the given type and it is the current default; retain the backed-up volume and mute values and report that a different device was used.
- If output selection is ambiguous or no output is present, skip live audio settings instead of silently targeting a potentially unrelated device.
- Restore other valid desktop settings even if the live audio device cannot be safely resolved. Report `Partially restored` and provide explicit details; do not falsely report total success.
- Continue to make safety snapshots of user files and current audio before applying changes. All-or-nothing strict mode for programmatic callers is unchanged.
- No alteration to RPM/Zypper filters, package installs or removal, Refresh, or other desktop backends.

## Practical test on the openSUSE virtual machine

1. Install the newly built `.flatpak`. Existing `.bu` archives can be opened; their saved audio device name is not rewritten.
2. On openSUSE, run `pactl get-default-sink` and `pactl list short sinks` before changing anything; save the output if restore still fails.
3. Create a fresh desktop settings backup with Display + Audio + another KDE category selected (when testing a fresh capture). An older backup can also be used specifically to exercise the changed-name fallback.
4. Adjust resolution and audio volume, then restore the backup. Confirm any warning names the audio device mapping or clearly says the live audio was skipped.
5. If no safe audio device match exists, confirm that other settings still restore, that the audio volume is not silently changed and that the result is **Partially restored**, not **Restored**.
6. Reboot, then check resolution, audio, panel, theme, wallpaper, power and remaining selected KDE settings separately. Automatic tests do not prove persistence in an actual Plasma session.

## Diagnostics (read-only)

```bash
pactl get-default-sink
pactl list short sinks
pactl get-default-source
pactl list short sources
```

A currently unavailable audio device cannot be recreated by the application. Multiple outputs are never guessed. Restore warnings must be treated as actionable, not as a full pass.

README changes about openSUSE password prompts and the planned Info/ratings features are intentionally postponed until openSUSE testing is complete.
