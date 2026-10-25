"""Bounded host-session audio snapshot for local settings backups.

PulseAudio-compatible `pactl` also works when PipeWire provides pipewire-pulse.
Only the active default devices, their volumes and mute states are retained.
The backup is personal, local and intentionally not encrypted.
"""
import re

DEVICE = re.compile(r'^[A-Za-z0-9_.:+-]{1,255}$')


def _call(run, args):
    if run is None:
        raise RuntimeError('Host audio commands unavailable; audio settings were not saved.')
    ok, out, err = run(['pactl'] + args, 20)
    if not ok:
        raise RuntimeError('Host audio control failed: pactl ' + ' '.join(args[:2]) +
                           ' — ' + str(err or out or 'unavailable').strip()[:300] +
                           '. For Ubuntu/Xubuntu check that pulseaudio-utils and the audio server are running.')
    return str(out).strip()


def validate(state):
    if not isinstance(state, dict) or state.get('backend') != 'pactl' or set(state) != {'backend','sink','source'}:
        raise ValueError('Invalid audio snapshot format')
    if state.get('sink') is None:
        raise ValueError('Backup has no active audio output device')
    for item in ('sink', 'source'):
        value = state[item]
        if value is None:
            continue
        if not isinstance(value, dict) or set(value) != {'name','volume','muted'}:
            raise ValueError('Invalid audio device snapshot')
        if not isinstance(value['name'], str) or not DEVICE.fullmatch(value['name']):
            raise ValueError('Unsafe audio device name')
        if type(value['volume']) is not int or not 0 <= value['volume'] <= 150:
            raise ValueError('Invalid audio volume')
        if type(value['muted']) is not bool:
            raise ValueError('Invalid audio mute setting')
    return state


def _read_device(run, name, role):
    if not DEVICE.fullmatch(name):
        raise ValueError('Unsafe host audio device name')
    raw = _call(run, [f'get-{role}-volume', name])
    volumes = [int(value) for value in re.findall(r'\b(\d{1,3})%', raw)]
    if not volumes:
        raise RuntimeError('Cannot identify the current volume for ' + name)
    # pactl can expose separate channel levels; do not silently lose balance.
    if len(set(volumes)) != 1:
        raise RuntimeError('Audio has different left/right levels; this backup version cannot preserve channel balance.')
    mute = _call(run, [f'get-{role}-mute', name]).lower()
    if mute not in ('mute: yes', 'mute: no'):
        raise RuntimeError('Cannot read current mute state for ' + name)
    return {'name':name, 'volume':volumes[0], 'muted':mute.endswith('yes')}


def capture_audio_state(run):
    """Read live values on the host; failure is not a successful empty backup."""
    _call(run, ['info'])
    sink = _call(run, ['get-default-sink']).splitlines()[0].strip()
    if not sink:
        raise RuntimeError('No default audio output found')
    source = _call(run, ['get-default-source']).splitlines()[0].strip()
    state = {'backend':'pactl', 'sink':_read_device(run, sink, 'sink'),
             'source': _read_device(run, source, 'source') if source else None}
    return validate(state)


def prepare_audio_restore(run, state):
    """Resolve renamed audio devices without guessing among several outputs.

    The saved *volume and mute* are applied to a new default only if the host
    exposes exactly one available device of that type. Multiple candidates
    are ambiguous: never select one silently. An unavailable microphone may
    be skipped while still restoring the confirmed output.

    No audio state is changed here; the caller can safely preflight first.
    """
    validate(state)
    result = {'backend': 'pactl', 'sink': dict(state['sink']),
              'source': dict(state['source']) if state['source'] else None}
    warnings = []
    for role in ('sink', 'source'):
        item = result[role]
        if item is None:
            continue
        installed = _call(run, ['list', 'short', role + 's'])
        names = {line.split('\t')[1] for line in installed.splitlines()
                 if len(line.split('\t')) > 1 and DEVICE.fullmatch(line.split('\t')[1])}
        if item['name'] in names:
            continue
        current_default = _call(run, ['get-default-' + role]).splitlines()[0].strip()
        if len(names) == 1 and current_default in names:
            item['name'] = current_default
            warnings.append('Saved audio ' + role + ' device name changed; '
                            'volume and mute were applied to the only available '
                            'default device (' + current_default + ').')
        elif role == 'source':
            warnings.append('Saved microphone device is unavailable or ambiguous; '
                            'microphone settings were not restored (' + item['name'] + ').')
            result['source'] = None
        else:
            raise RuntimeError('Saved audio sink is unavailable or ambiguous on this computer: '
                               + item['name'] + '. Available outputs: '
                               + (', '.join(sorted(names)) or '(none)'))
    validate(result)
    return result, warnings


def apply_audio_state(run, state):
    """Refuse missing devices BEFORE changing sound settings."""
    validate(state)
    for role in ('sink','source'):
        device = state[role]
        if device is None:
            continue
        installed = _call(run, ['list', 'short', role+'s'])
        names = {line.split('\t')[1] for line in installed.splitlines() if len(line.split('\t')) > 1}
        if device['name'] not in names:
            raise RuntimeError('Saved audio ' + role + ' is unavailable on this computer: ' + device['name'])
    for role in ('sink','source'):
        device = state[role]
        if device is None: continue
        _call(run, ['set-default-'+role, device['name']])
        _call(run, ['set-'+role+'-volume', device['name'], str(device['volume'])+'%'])
        _call(run, ['set-'+role+'-mute', device['name'], '1' if device['muted'] else '0'])
    # The command returning exit status 0 does not prove that the audio server
    # accepted the requested state. Fail visibly (and let the caller roll back)
    # if the current default/volume/mute differs after the update.
    actual = capture_audio_state(run)
    for role in ('sink', 'source'):
        expected_device, actual_device = state[role], actual[role]
        if expected_device is None:
            continue
        if (actual_device is None or actual_device['name'] != expected_device['name'] or
                actual_device['muted'] != expected_device['muted'] or
                abs(actual_device['volume'] - expected_device['volume']) > 1):
            raise RuntimeError('Audio ' + role + ' was not restored: current volume, '
                               'mute or default device differs from the backup')
    return True
