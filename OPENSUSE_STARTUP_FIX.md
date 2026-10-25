# openSUSE start failure — audio_backup module missing

Observed on openSUSE 16.0 KDE:

```
File "/app/bin/universal_backup.py", line 17
    from audio_backup import capture_audio_state, apply_audio_state, validate as validate_audio_state
ModuleNotFoundError: No module named 'audio_backup'
```

## Root cause

The previous source ZIP **contained** `audio_backup.py`, but the Flatpak JSON
manifest omitted it from both `sources` and the `install -Dm644 ... /app/bin` 
build commands. Local Python unittest runs succeeded because the module was
present in the source directory, while the built Flatpak did not contain it.

## Fixed

- Add `audio_backup.py` to the Flatpak module sources and its install commands.
- Add `scripts/check-packaging.py` to ensure that **every** top-level Python
  module is listed and installed. This check runs before the Flatpak build.
- Verify staged `/app/bin/*.py` files after Flatpak Builder finishes and BEFORE
  creating a distributable bundle.
- Compile all top-level source modules and add targeted regression tests.

No application behavior, Backup/Restore data format, wording or UI was changed.

## Build on Bazzite

Extract ZIP. Open its folder in Dolphin, press F4, run:

```
bash scripts/build-bundle.sh UniversalLinuxSoftwareManager-v1.0.0-openSUSE-startup-fix.flatpak
```

Transfer the resulting .flatpak to your openSUSE VM using the already-working
Remote Viewer and install the new bundle. To avoid confusion with earlier
bundles, do not rename an older Flatpak to the fixed bundle's filename.

## Validation

Static tests and packaging tests are runnable on the development machine.
The full actual Flatpak packaging/build and live startup must be tested on
Bazzite/openSUSE; these cannot be proven by only running Python unittest.
