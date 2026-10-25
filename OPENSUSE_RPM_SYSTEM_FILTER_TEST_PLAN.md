# openSUSE Plasma 6 — RPM System Component Filter

Problem observed on openSUSE Leap 16.0: RPM displayed Plasma 6 package IDs
because those RPMs own .desktop launchers. A desktop launcher is not proof
that a package is an optional application.

## Change

- Hide KDE Plasma runtime/workspace components and package families such as
  `plasma6-*`, `plasma5-*`, `libplasma6-*`, `kf6-*` and KDE system KCMs.
- The same protected-package test is applied to RPM preflight removal,
  even if the GUI selection becomes stale.
- Do not change RPM installation logic, GNOME/KDE Backup/Restore,
  refresh buttons, or other tabs.

## Tests on openSUSE Leap 16.0 Plasma

1. Install the rebuilt Flatpak and open the RPM tab; click Refresh.
2. Search `plasma6`: no package IDs beginning `plasma6-` should appear.
3. Search `libplasma`, `kf6`, `kwin`, `powerdevil`: system components should not appear.
4. Confirm explicitly installed graphical software (e.g. Brave or VLC)
   remains visible when supplied by an RPM and owning a desktop launcher.
5. Do NOT remove actual system packages for testing. The automated tests
   exercise the protected-package refusal without modifying the host.

**Limitation:** Linux distributions do not have one reliable universal flag
for all default/essential desktop packages. This conservative known-family
filter blocks common KDE infrastructure, but cannot prove all other RPMs are
user-installed or safe to remove. Dependency preflights remain mandatory.
