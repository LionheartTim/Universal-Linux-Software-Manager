"""Safe, branch-specific Flatpak removal helpers.

Flatpak can install different app branches under the same ID and installation.
Bare IDs can therefore trigger an interactive choice and are unsuitable for
our noninteractive GUI. Only exact, host-confirmed references are permitted.
"""
import re
from dataclasses import dataclass

ATOM = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]*\Z')


@dataclass(frozen=True)
class FlatpakRef:
    application: str
    installation: str
    ref: str


def valid_app_ref(app_id, ref):
    if not isinstance(app_id, str) or not isinstance(ref, str):
        return False
    parts = ref.split('/')
    return (len(parts) == 4 and parts[0] == 'app' and
            parts[1] == app_id and '.' in app_id and
            all(ATOM.fullmatch(v) for v in parts[1:]))


def valid_location(value):
    return isinstance(value, str) and bool(ATOM.fullmatch(value))


def parse_installed(output, *, columns='identity'):
    """Parse Flatpak --columns=application,installation,ref (or GUI columns).

    Fail closed on missing refs or malformed Flatpak output. Unlike the display
    version, the 'ref' field contains the exact *branch* and architecture.
    """
    if not isinstance(output, str):
        raise ValueError('Invalid Flatpak listing')
    rows = []
    for lineno, line in enumerate(output.splitlines()):
        if not line.strip():
            continue
        parts = [x.strip() for x in line.split('\t')]
        if columns == 'gui':
            if len(parts) != 5:
                raise ValueError('Incomplete Flatpak GUI listing')
            _name, app_id, _version, location, ref = parts
        elif columns == 'identity':
            if len(parts) != 3:
                raise ValueError('Incomplete Flatpak identity listing')
            app_id, location, ref = parts
        else:
            raise ValueError('Unknown Flatpak listing schema')
        if lineno == 0 and app_id.casefold() in ('application', 'applicatie') and ref.casefold() == 'ref':
            continue
        if not valid_app_ref(app_id, ref) or not valid_location(location):
            raise ValueError('Flatpak list lacks safe, exact app references')
        rows.append(FlatpakRef(app_id, location, ref))
    return rows



def parse_inventory(output, *, gui=False):
    """Read explicit arch/branch columns and create exact refs locally.

    Flatpak's visible 'ref' column is not reliably shaped the same way on
    every released host. Asking for the four constituent fields avoids
    rejecting all apps when a reference is formatted differently.

    Expected columns (GUI): name, application, version, arch, branch,
    installation. Verification uses application, arch, branch, installation.
    Invalid records fail closed rather than producing guessed references.
    """
    if not isinstance(output, str):
        raise ValueError('Invalid Flatpak listing')
    result = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split('\t')]
        if len(parts) != (6 if gui else 4):
            raise ValueError('Incomplete Flatpak list columns')
        if gui:
            name, app_id, version, arch, branch, installation = parts
        else:
            app_id, arch, branch, installation = parts
            name = version = ''
        # The Flatpak CLI may print an English or localized header.
        # It is not an installed reference.
        if app_id.casefold() in ('application', 'applicatie') and arch.casefold() in ('arch', 'architectuur'):
            continue
        ref = f'app/{app_id}/{arch}/{branch}'
        if not valid_app_ref(app_id, ref) or not valid_location(installation):
            raise ValueError('Flatpak list lacks safe, exact application identity')
        identity = FlatpakRef(app_id, installation, ref)
        result.append((name, version, identity) if gui else identity)
    if gui and not result and output.strip():
        raise ValueError('No verified Flatpak applications in listing')
    return result

def plan_uninstall(selected, installed, *, delete_data=False):
    """Compute a single exact-ref removal, never an ID-wide removal.

    The selection must still exist in the fresh host listing; never trust stale
    GUI state. Data can be deleted only if no other branch or location exists.
    """
    if not isinstance(selected, FlatpakRef) or not all(isinstance(r, FlatpakRef) for r in installed):
        raise ValueError('Invalid Flatpak selection')
    if not valid_app_ref(selected.application, selected.ref) or not valid_location(selected.installation):
        raise ValueError('Invalid Flatpak selection reference')
    if installed.count(selected) != 1:
        raise ValueError('The selected Flatpak ref changed or is not uniquely installed')
    same_app = [r for r in installed if r.application == selected.application]
    if delete_data and len(same_app) != 1:
        raise ValueError('Other Flatpak branches exist; shared user data must be kept')
    loc = selected.installation
    if loc == 'user':
        flag = '--user'
    elif loc in ('system', 'default'):
        flag = '--system'
    else:
        flag = '--installation=' + loc
    args = ['flatpak', 'uninstall', flag, '--noninteractive', '-y']
    if delete_data:
        args.append('--delete-data')
    args.append(selected.ref)
    return args


def verify_removed(selected, installed):
    """True only if exact ref is absent after a successful Flatpak command."""
    if not isinstance(selected, FlatpakRef) or not all(isinstance(r, FlatpakRef) for r in installed):
        raise ValueError('Invalid Flatpak verification data')
    return selected not in installed
