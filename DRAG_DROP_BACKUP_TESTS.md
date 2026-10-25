# Universal Linux Software Manager v1.0.0 — Drag-and-drop backup tests

1. Open Backup / Restore and drop **one known safe local AppImage installer** onto the package table.
2. Verify name, format and size appear; no installation should start.
3. Optionally check a harmless KDE appearance setting. Click Create local ZIP backup and save it outside `~/Applications`.
4. Open the saved ZIP, select the file and click Install selected backup file. The exact installer should be extracted, checked and handed to the AppImage tab.
5. Do not test restoring over an existing AppImage of the same filename: first use a separate test filename or uninstall the earlier test version with the regular AppImage tab.
6. After confirmation verify it appears in AppImage and launches. Test with invalid/tampered ZIP and reject fake RPM/DEB and `.flatpakref` files.
7. Then test a **real** `.flatpak` bundle, watching for runtime dependencies. RPM/DEB/Arch/Snap installs must only be tried on compatible **non-critical** test machines/distributions.
8. Restore KDE settings only after making a separate recovery copy and only when the desktop family matches.

**Important:** A SHA-256 hash stored inside a backup detects later corruption; it does not authenticate a publisher. A local RPM is not portable to a Debian system; a `.flatpak` bundle does not necessarily include its runtimes. ZIP files and optional user settings are not encrypted. No cloud upload occurs.

The new package-file archive format is distinct from older application-list JSON / desktop-settings ZIP backups. It must not be interpreted as an automatic promise of offline full-system recovery.

### Two-button layout

The main actions are **Create backup...** and **Restore backup...**. Drag files or use **Add files...**, and remove only selected items with **Remove from backup selection**. There is no separate Clear list button. After opening an existing backup, Add files can start a new draft after confirmation; the original ZIP stays intact. Restore currently works **per selected installer file**, while desktop settings use their own confirmation; it does not yet restore all packages and settings in one automatic pass.
