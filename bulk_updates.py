"""Conservative, Qt-independent planning for a sequential 'Update all' action.

No package source changes, automatic native-system upgrades, or guessed GitHub
repository associations. The GUI owns the confirmation and executes one job
at a time. This planner does not mutate the host.
"""

def plan_update_all(entries, upgrade_command, manager, choose_appimage,
                    package_is_protected, available):
    """Return (runnable [(entry, argv_or_None)], skipped [(entry, reason)]).

    The entire installed inventory is considered, independent of the current
    search or 'updates available only' view. A (kind,id,scope) is updated once.
    """
    ready, skipped, visited = [], [], set()
    for entry in entries:
        if entry.get('status') != 'available':
            continue
        key = (entry.get('kind'), entry.get('id'), entry.get('scope'))
        if key in visited:
            continue
        visited.add(key)
        kind = entry.get('kind')
        if kind == 'AppImage':
            release = entry.get('release')
            if not entry.get('github_repo') or not release or not choose_appimage(release):
                skipped.append((entry, 'No verified GitHub AppImage release'))
            else:
                ready.append((entry, None))
            continue
        if package_is_protected(entry.get('id','')):
            skipped.append((entry, 'Protected system package'))
            continue
        try:
            args = upgrade_command(entry, manager)
        except (ValueError, TypeError, KeyError):
            args = None
        if not args:
            skipped.append((entry, 'No safe update command for this distribution'))
        elif args[0] == 'pkexec' and not available('pkexec'):
            skipped.append((entry, 'Polkit authorization is unavailable'))
        else:
            ready.append((entry, args))
    return ready, skipped


def update_all_summary(results, skipped_before=()):
    """Results are (entry, outcome, detail); outcome=updated/skipped/failed."""
    updated = sum(outcome == 'updated' for _, outcome, _ in results)
    skipped = len(skipped_before) + sum(outcome == 'skipped' for _, outcome, _ in results)
    failed = sum(outcome == 'failed' for _, outcome, _ in results)
    return {'updated': updated, 'skipped': skipped, 'failed': failed}
