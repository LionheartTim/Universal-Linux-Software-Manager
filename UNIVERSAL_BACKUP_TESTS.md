# v1.0.0 — universal settings backup & source adapters (development only)

**Do not publish yet.** The project's Flatpak runtime cannot be tested in the build environment, and source adapters have not been checked on actual Alpine/Void/Gentoo/NixOS hosts.

## Scope

- Six original package-install tabs retained.
- Updates: all supported installed package types, with status labels for unsafe/unimplemented native package updates; no speculative installation of unsupported native upgrades.
- Discover: remains strictly **read-only**, including extra distro repository searches.
- Backup: optional individual application checkbox list plus KDE, GNOME, Cinnamon, MATE, Xfce and LXQt-specific settings, shared audio settings and optional Flatpak app preferences.

## Local backup checks

1. Create ZIP with Display and Appearance only. Inspect that only allowlisted config files were copied.
2. Create ZIP with Installed applications alone and verify no personal application config.
3. With explicit opt-in, include one selected Flatpak's `~/.var/app/APP_ID/config` and verify other apps are excluded.
4. Import backup; a different desktop can restore the app list (and separately app prefs), not KDE/other desktop config.
5. Restore a harmless test setting; prior config must be present under `restore-history`.
6. Corrupted ZIP members, symlinked destinations, wrong desktop type, oversized archives must fail.

**Privacy:** The archive is unencrypted and may include account tokens if opted-in. Never send it to someone else unless separately encrypted.

**Compatibility:** This design uses capability probes, not Bazzite-specific paths for native package operations. Some native package backends are deliberately read-only/partial and need on-distro tests. This is not a guarantee of complete cross-distro support.
