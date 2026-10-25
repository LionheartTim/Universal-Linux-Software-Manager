# Info / F1 Help — v1.0.0 test

This preview adds the **tenth Info tab** to the current KDE Universal Next Login Restore baseline. The existing package operations, Backup/Restore behavior, and other nine tabs are unchanged.

## What is included

- English-only, **offline** help (no WebEngine or network calls)
- Left-hand expanding contents tree and clickable topic links inside the guide
- Home, Back, Forward, search / Find next, and Ctrl+F when Info is active
- F1 opens the appropriate chapter from Flatpak, AppImage, RPM, DEB, Arch, Snap, Updates, Discover or Backup/Restore
- Chapters: Getting Started, differences between all six packages, native dependency managers, installation/removal, Updates, read-only Discover, `.bu` backup, KDE one-shot next-login restore, other desktop settings, permissions, troubleshooting, FAQ, shortcuts, feedback
- Source files `info_help.py` and `help_content.py` installed inside the Flatpak (verified by `scripts/check-packaging.py`)

## Manual test on the host

1. Build and install the new `.flatpak` using the existing `scripts/build-bundle.sh` build flow.
2. Open the app. Check that **Info** appears to the right of **Backup / Restore** and all existing tabs remain.
3. Click **Info**. Its table of contents should appear immediately, with an expanded chapter tree at left.
4. Click a topic in the left tree; it should jump to the chapter. Click **Back to contents** inside the text; it should return to the table of contents. Verify Home / Back / Forward navigation.
5. Search for `KWin` and press Enter several times; the document should move through matches, wrapping at the end. Press Ctrl+F while in Info to focus the search box.
6. Open the **RPM** tab and press **F1**. Verify that Info opens at the RPM chapter. Repeat for **Backup / Restore** and **Discover**.
7. Verify that fonts, table borders and links are readable in both your chosen Plasma theme and window size.
8. Close/reopen the app and verify normal package tab operation; test that package operations and KDE next-login restore were not modified.

## Validation and limitations

Unit tests and packaging checks verify documentation integrity and GUI code wiring, but do not replace a real PyQt6 runtime smoke test. This test edition does **not** add Discover ratings, which are a separate planned feature. The detailed README explanation for repeated authentication prompts during GUI installation is not part of this change.
