# v1.0.0 — Update all: Bazzite GUI test plan

## Expected behavior

- The **Updates** tab offers **Update all** instead of **Update selected**.
- Once an update scan has identified one or more available updates, **Update all** is enabled even with no row selected.
- Search and **Updates available only** affect the table display, **not** which eligible updates run. **Update all** always means the full set of safely updateable candidates in the most recent scan.
- Clicking the button shows a confirmation listing the candidate apps and count, along with any skipped unsafe/unsupported candidates. No packages change until the user chooses **Yes** (default is No).
- Updates execute **one at a time** using the original source and appropriate package manager. No full OS or unsafe Arch partial upgrade is attempted.
- A tracked GitHub AppImage is downloaded and verified first, then prompts separately whether to replace the old file. **No** skips only that AppImage.
- After a package failure the queue **stops**. The remaining applications are left untouched.
- The completion dialog shows updated/skipped/failed counts with per-item details; installed lists and Updates are refreshed once the batch ends.
- Closing the application while a batch is active remains blocked by the existing busy guard.

## Quick practical checks (safe test)

1. On Bazzite, scan updates while no table row is selected, ideally with one or more Flatpak applications showing **Update available**.
2. Verify **Update all** is clickable. With the checkbox on and off it should remain clickable when updates are available.
3. Click **Update all**, inspect the app names/count, then choose **No**. Confirm nothing was updated.
4. Click again, choose **Yes**. Observe one package operation at a time. If it involves a GitHub AppImage, choose **No** at the replacement confirmation to verify skip status.
5. Confirm the final summary and refreshed available-update list. Test actual app functionality after updating.
6. For an error test, prefer a harmless offline/no-network attempt or an isolated VM; do not intentionally interrupt a production package transaction.

## Limits

- 209 Python tests currently pass locally. PyQt6 is unavailable in the test container, so a real Bazzite graphical test is still required.
- An update may change Flatpak commits while the visible version string remains unchanged.
- A host package manager may still request authorization or reject an update. This app never silently retries a failed batch transaction.
