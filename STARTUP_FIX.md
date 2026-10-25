# v1.0.0 Startup Fix — DiscoverPanel

Problem: App crashed at startup with `AttributeError: DiscoverPanel has no attribute update_mark_label`.

Correction: Remove an accidental `itemSelectionChanged.connect(self.update_mark_label)` line in `DiscoverPanel`. The existing `update_open_button` signal and all Discover read-only behavior are preserved.

Regression checks: `tests/test_gui_startup_wiring.py` checks the existence of all directly connected widget callbacks, verifies Discover is not editable, and checks all nine tab constructors are present.

No version number, Flatpak ID, icon or user data changes.
