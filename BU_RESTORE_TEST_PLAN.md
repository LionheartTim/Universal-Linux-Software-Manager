# .bu Backup / Restore — practical test plan (v1.0.0 preview)

Universal Linux Software Manager uses a structured `.bu` local archive based on ZIP, with `manifest.json`, hashes, selected package installer files, and optional desktop settings. `.bu` is a filename extension, NOT encryption or an access restriction; standard ZIP readers can open it. No script embedded inside the archive is executed. Older compatible `.zip` backups remain supported for reading.

## Create

1. Open **Backup / Restore**. Drag a *trusted, disposable* direct `.AppImage` into the list (or click **Add files**). Optionally check one safe desktop setting.
2. Click **Create backup**. Save as `test.bu`.
3. Confirm the `Backup succeeded` popup. **Before** clicking OK, verify the
   file list remains visible. **After** OK, verify the table and settings choices
   return to the empty initial state, without deleting the `.bu` file.

## Restore overview and queue

1. Click **Restore backup**, select `test.bu`.
2. Check that every saved installer appears with **Waiting for approval** in the **Status** column. Optional desktop settings appear as an extra row. A `Backup opened` dialog explains that another click on **Restore backup** starts the queue.
3. Click **Restore backup** again to start. A prompt appears for each installer.
   Choose **No** first; verify **Skipped** and that no installation begins.
   At the end, inspect the popup (should **not** say `Restore succeeded` when
   items were skipped), then click OK. Only then should the list reset to empty.
4. Reopen `test.bu` and repeat with **Yes** for a *safe test package*. Observe **Verifying...**, **Installing...**, then **Installed** or **Failed** depending on the actual installer job outcome. If the installer reports an rpm-ostree staged operation, status is **Reboot required**.
5. Test **Cancel** on a prompt: the queue stops without processing the remaining installers.
6. When settings were included, their own row requires a separate explicit **Yes** and is subject to desktop compatibility checks.
7. Test an incompatible RPM on a distro without RPM support: it must show **Unavailable**, NOT installed.
8. Confirm that no automatic shell script from the `.bu` archive runs, no package is installed without explicit consent, and package files are cleaned from temporary staging after use.

Never test native restore using a system-critical package. Real user-facing GUI, package-manager, and cross-distro behavior must be checked on the target Linux systems before public release.

## Final pop-up / reset regression

- On an entirely successful restore, the modal title is `Restore succeeded`;
  for a failed, unsupported or interrupted restore, it must not claim success.
- `Details` lists every app's outcome before the modal closes. The modal also
  indicates if a reboot is required or the queue was cancelled.
- Closing the final modal resets the list and checkboxes to the initial state;
  `.bu` files, installed programs and rollback copies remain untouched.
- On a failed backup write, source selections are **not** cleared.
