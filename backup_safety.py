"""Pure local safety checks for .bu create/restore operations.

These are *preflight checks*, never a promise that package dependencies,
permissions or post-install scripts will succeed. No commands from archives run.
"""
from pathlib import Path

MARGIN = 64 * 1024 * 1024  # Free-space headroom for streaming/staging.


def estimated_backup_bytes(paths, settings_bytes=0):
    """Destination needs an atomic copy of the original files, not just ZIP metadata."""
    sizes = [Path(p).stat().st_size for p in paths]
    # Settings ZIP is built alongside the destination and then embedded in it.
    return sum(sizes) + 2 * max(int(settings_bytes), 0) + MARGIN


def preflight_restore(meta, *, desktop, distro, architecture, available_kinds,
                      managers, free_bytes):
    """Return per-file blocking reasons and nonblocking cross-host warnings.

    The caller must have validated ZIP checksums with inspect_backup first.
    managers: kind -> usable native manager; available_kinds: package tabs with
    working install entrypoints. Neither is inferred from filename extension.
    """
    packages = meta.get('packages', [])
    source_arch = str(meta.get('architecture', '') or '')
    source_distro = set(meta.get('distro', []) or [])
    current_distro = set(distro)
    warnings, blocked, rows = [], {}, []
    settings = meta.get('settings')
    # Restoring settings temporarily holds both the nested ZIP and unpacked
    # user settings. Native packages may need extra space beyond this estimate.
    settings_bytes = int(settings['size']) if settings else 0
    stage_needed = max([int(p['size']) for p in packages] + [0]) + 2 * settings_bytes + MARGIN
    if source_distro and current_distro and not source_distro.intersection(current_distro):
        warnings.append('Distro differs from backup; native packages might not be compatible.')
    settings_desktop = str(meta.get('desktop', '') or '')
    if settings and settings_desktop not in ('', desktop):
        warnings.append('Different desktop environment: desktop settings are disabled for safety.')
        blocked['settings'] = 'Incompatible desktop environment; settings will not be applied.'
    if settings and 2 * settings_bytes + MARGIN > free_bytes:
        blocked['settings'] = 'Insufficient free space for settings extraction.'
    for index, item in enumerate(packages):
        kind = item['kind']
        size = int(item['size'])
        reasons = []
        if kind not in available_kinds or not managers.get(kind):
            reasons.append('No compatible installer or package manager is available.')
        if source_arch and source_arch != architecture and kind != 'Flatpak':
            reasons.append('CPU architecture differs from backup.')
        if size + MARGIN > free_bytes:
            reasons.append('Insufficient free space to stage this installer.')
        if kind not in ('Flatpak', 'AppImage') and source_distro and current_distro and not source_distro.intersection(current_distro):
            reasons.append('Native installer was saved on a different distribution family.')
        if reasons:
            blocked[index] = '; '.join(reasons)
        rows.append({'filename': item['filename'], 'kind': kind, 'bytes': size,
                     'eligible': not reasons, 'reasons': reasons})
    return {'blocked': blocked, 'rows': rows, 'warnings': warnings,
            'archive_distro': sorted(source_distro), 'host_distro': sorted(current_distro),
            'archive_arch': source_arch, 'host_arch': architecture,
            'archive_desktop': settings_desktop, 'host_desktop': desktop,
            'staging_required': stage_needed, 'free_bytes': int(free_bytes),
            'settings': bool(settings)}


def summarize_report(report, dutch=False):
    mib = 1024 * 1024
    allowed = sum(row['eligible'] for row in report['rows'])
    denied = len(report['rows']) - allowed
    if dutch:
        lines = [f'Apps geschikt voor herstel: {allowed}', f'Apps niet ondersteund: {denied}',
                 f'Vrije schijfruimte: {report["free_bytes"] / mib:.0f} MiB',
                 f'Grootste benodigde staging: circa {report["staging_required"] / mib:.0f} MiB',
                 f'Back-updistributie: {", ".join(report["archive_distro"]) or "onbekend"}',
                 f'Huidige distributie: {", ".join(report["host_distro"]) or "onbekend"}',
                 f'Desktopomgeving: {report["archive_desktop"] or "?"} → {report["host_desktop"]}',
                 f'Architectuur: {report["archive_arch"] or "?"} → {report["host_arch"]}']
    else:
        lines = [f'Apps eligible for restore: {allowed}', f'Apps unavailable: {denied}',
                 f'Free space: {report["free_bytes"] / mib:.0f} MiB',
                 f'Largest staging requirement: approx. {report["staging_required"] / mib:.0f} MiB',
                 f'Backup distro: {", ".join(report["archive_distro"]) or "unknown"}',
                 f'Current distro: {", ".join(report["host_distro"]) or "unknown"}',
                 f'Desktop: {report["archive_desktop"] or "?"} → {report["host_desktop"]}',
                 f'CPU architecture: {report["archive_arch"] or "?"} → {report["host_arch"]}']
    translations = {
        'Distro differs from backup; native packages might not be compatible.':
            'De distributie verschilt: native pakketten kunnen incompatibel zijn.',
        'Different desktop environment: desktop settings are disabled for safety.':
            'Andere desktopomgeving: terugzetten van instellingen wordt voor de veiligheid geblokkeerd.',
        'Insufficient free space for settings extraction.':
            'Onvoldoende ruimte om instellingen uit te pakken.',
        'Incompatible desktop environment; settings will not be applied.':
            'Incompatibele desktopomgeving; instellingen worden niet toegepast.',
        'No compatible installer or package manager is available.':
            'Geen geschikte installer of pakketbeheerder beschikbaar.',
        'CPU architecture differs from backup.':
            'Processorarchitectuur verschilt.',
        'Insufficient free space to stage this installer.':
            'Onvoldoende ruimte om dit installatiebestand uit te pakken.',
        'Native installer was saved on a different distribution family.':
            'Native pakket is afkomstig van een andere distributiefamilie.',
    }
    if report['warnings']:
        lines.append(('Waarschuwingen:' if dutch else 'Warnings:'))
        lines.extend('  • '+(translations.get(w,w) if dutch else w) for w in report['warnings'])
    if report['blocked']:
        lines.append(('Niet ondersteunde onderdelen:' if dutch else 'Unavailable items:'))
        blocked=list(report['blocked'].items())
        for row,reason in blocked[:4]:
            label = ('Desktopinstellingen' if dutch else 'Desktop settings') if row == 'settings' else report['rows'][row]['filename']
            lines.append(f'  {label}: {translations.get(reason,reason) if dutch else reason}')
        if len(blocked) > 4:
            lines.append(('  ... en nog ' if dutch else '  ... and ') + str(len(blocked)-4))
    lines.append(('Let op: extra ruimte voor pakketafhankelijkheden is niet meegerekend.' if dutch else 'Note: extra space for package dependencies is not included.'))
    lines.append(('Er worden nog geen wijzigingen uitgevoerd.' if dutch else 'No changes have been made yet.'))
    lines.append(('Klik nogmaals op Restore backup om te beginnen.' if dutch else 'Click Restore backup again to start.'))
    return '\n'.join(lines)
