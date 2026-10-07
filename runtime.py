"""Isolate persistent user state from disposable game storage projections."""
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import subprocess
import signal


def isolate_home(prefix):
    prefix = Path(prefix).resolve()
    users = prefix / 'drive_c' / 'users'
    if not users.is_dir():
        raise ValueError('Wine prefix has not been initialized')
    for user in users.iterdir():
        if user.is_symlink() or not user.is_dir():
            continue
        for name in ('Desktop', 'Documents', 'Downloads', 'Music', 'Pictures', 'Videos', 'My Documents'):
            path = user / name
            if path.is_symlink() and not path.resolve().is_relative_to(prefix):
                # Remove only the link in our prefix; preserve the host folder.
                path.unlink()
                path.mkdir()


def prepare_game(content, destination):
    """Fresh private projection: no previous runtime writes become inputs.

    CASC opens archives writable even to validate/read them. Linux FICLONE and macOS APFS clonefile
    share source blocks until a private write; other filesystems copy bytes.
    Both paths preserve the immutable store and discard game writes on exit.
    """
    content = Path(content).resolve()
    destination = Path(destination)
    if destination.exists():
        raise ValueError('game projection already exists')
    # Validate before creating output; never follow arbitrary runtime links.
    paths = sorted(content.rglob('*'))
    if not content.is_dir() or any(p.is_symlink() or not (p.is_dir() or p.is_file()) for p in paths):
        raise ValueError('unsupported entry in immutable game content')
    destination.mkdir(mode=0o700)
    for source in paths:
        target = destination / source.relative_to(content)
        if source.is_dir():
            target.mkdir(mode=0o700)
            continue
        if sys.platform == 'darwin':
            # APFS clonefile preserves signed bytes and uses copy-on-write.
            import ctypes
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.clonefile(os.fsencode(source), os.fsencode(target), 0) == 0:
                target.chmod(0o600 | (source.stat().st_mode & 0o111))
                continue
            if ctypes.get_errno() not in (errno.EXDEV, errno.EOPNOTSUPP, errno.ENOTSUP, errno.EINVAL):
                raise OSError(ctypes.get_errno(), 'clonefile failed')
        with source.open('rb') as reader, target.open('xb') as writer:
            try:
                if sys.platform != 'darwin':
                    fcntl.ioctl(writer.fileno(), 0x40049409, reader.fileno())  # FICLONE
                else:
                    shutil.copyfileobj(reader, writer, 1024 * 1024)
            except OSError as error:
                if error.errno not in (errno.EXDEV, errno.EOPNOTSUPP, errno.ENOTTY, errno.EINVAL):
                    raise
                writer.seek(0)
                writer.truncate()
                shutil.copyfileobj(reader, writer, 1024 * 1024)
        target.chmod(0o600 | (source.stat().st_mode & 0o111))


def persist_directories(game, state, directories):
    """Expose selected user directories inside a disposable projection."""
    game = Path(game).resolve()
    state = Path(state)
    paths = [Path(name) for name in directories]
    if any(not name or path.is_absolute() or '..' in path.parts or path == Path('.')
           for name, path in zip(directories, paths)):
        raise ValueError('persistent directories must be relative paths')
    if len(set(paths)) != len(paths) or any(
            a != b and a in b.parents for a in paths for b in paths):
        raise ValueError('persistent directories overlap')
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    if state.is_symlink():
        raise ValueError('persistent state root must not be a symlink')
    for relative in paths:
        target = game / relative
        saved = state / relative
        # Never redirect writes through a replaced root or parent directory.
        for root, path in ((game, target), (state, saved)):
            current = path
            while current != root:
                if current.is_symlink() or (current.exists() and not current.is_dir()):
                    raise ValueError('persistent directory overlaps a file or symlink')
                current = current.parent
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        saved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not saved.exists():
            if target.exists():
                shutil.move(str(target), str(saved))
            else:
                saved.mkdir(mode=0o700)
        elif target.exists():
            shutil.rmtree(target)
        target.symlink_to(saved.resolve(), target_is_directory=True)


def update_preferences(path, values, syntax):
    """Manage named keys while retaining other client preferences."""
    path = Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('client preferences must be a regular file')
    if syntax not in ('assign', 'wtf'):
        raise ValueError('unsupported preference syntax')
    if any(not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9]*', key)
           or not re.fullmatch(r'[a-zA-Z0-9]+', value) for key, value in values.items()):
        raise ValueError('invalid managed preference')
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_bytes().decode('utf-8-sig') if path.exists() else ''
    newline = '\r\n' if '\r\n' in text else '\n'
    pattern = re.compile(r'^\s*' + (r'SET\s+(\w+)\s+' if syntax == 'wtf' else r'(\w+)\s*='), re.I)
    owned = {key.lower(): (key, value) for key, value in values.items()}
    seen = set()
    lines = []
    for line in text.splitlines(keepends=True):
        match = pattern.match(line)
        key = match.group(1).lower() if match else None
        if key in owned:
            if key in seen:
                continue
            name, value = owned[key]
            line = (f'SET {name} "{value}"' if syntax == 'wtf' else f'{name}={value}') + newline
            seen.add(key)
        lines.append(line)
    if lines and not lines[-1].endswith(('\r', '\n')):
        lines[-1] += newline
    for key, (name, value) in owned.items():
        if key not in seen:
            lines.append((f'SET {name} "{value}"' if syntax == 'wtf' else f'{name}={value}') + newline)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix='.battlenet-settings-')
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as output:
            output.write(''.join(lines))
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def apply_settings(prefix, game, settings):
    prefix = Path(prefix).resolve()
    users = prefix / 'drive_c' / 'users'
    for entry in settings:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('invalid preference path')
        if entry['location'] == 'game':
            destinations = [Path(game) / relative]
        elif entry['location'] == 'documents':
            destinations = [user / 'Documents' / relative for user in users.iterdir()
                            if user.is_dir() and not user.is_symlink() and user.name.lower() != 'public']
            if not destinations:
                raise ValueError('Wine user profile is missing')
            if any(not path.resolve().is_relative_to(prefix) for path in destinations):
                raise ValueError('Wine Documents directory is outside its isolated prefix')
        else:
            raise ValueError('unsupported preference location')
        for destination in destinations:
            update_preferences(destination, entry['values'], entry['syntax'])


def run_native(settings, arguments):
    from ngdp import verify_install
    content = Path(settings['content'])
    release = json.loads(Path(settings['release']).read_text())
    for name in ['executable', 'workingDirectory']:
        path = Path(settings[name])
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('invalid native runtime path')
    for entry in settings['clientSettings']:
        path = Path(entry['path'])
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('invalid native preference path')
    state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'battlenet' / settings['generation']
    state.mkdir(parents=True, exist_ok=True)
    with (state / 'runtime.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('This build is already running')
        verify_install(content, release)
        with tempfile.TemporaryDirectory(dir=state, prefix='session.') as session:
            game = Path(session) / 'game'
            prepare_game(content, game)
            persist_directories(game, state / 'game-state', settings['persistentDirectories'])
            for entry in settings['clientSettings']:
                if entry['location'] == 'game':
                    path = game / entry['path']
                elif entry['location'] == 'documents':
                    path = Path.home() / 'Library/Application Support/Blizzard' / entry['path']
                else:
                    raise ValueError('unsupported native preference location')
                update_preferences(path, entry['values'], entry['syntax'])
            executable = game / settings['executable']
            if not executable.is_file() or not executable.resolve().is_relative_to(game):
                raise ValueError('native executable is missing or outside the projection')
            process = subprocess.Popen([str(executable), *settings['args'], *arguments],
                                       cwd=game / settings['workingDirectory'], start_new_session=True)
            handlers = {}
            def forward(signum, frame):
                if process.poll() is None:
                    os.killpg(process.pid, signum)
            for signum in (signal.SIGINT, signal.SIGTERM):
                handlers[signum] = signal.signal(signum, forward)
            try:
                return process.wait()
            finally:
                # Helpers in our child process group cannot retain a discarded
                # session after the main native client exits.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                for signum, handler in handlers.items():
                    signal.signal(signum, handler)


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == 'run-native':
        raise SystemExit(run_native(json.loads(Path(sys.argv[2]).read_text()), sys.argv[3:]))
    elif len(sys.argv) == 4 and sys.argv[1] == 'prepare-game':
        prepare_game(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 4 and sys.argv[1] == 'persist-directories':
        persist_directories(sys.argv[2], sys.argv[3], sys.argv[4:])
    elif len(sys.argv) == 5 and sys.argv[1] == 'apply-settings':
        apply_settings(sys.argv[2], sys.argv[3], json.loads(Path(sys.argv[4]).read_text()))
    elif len(sys.argv) == 2:
        isolate_home(sys.argv[1])
    else:
        raise SystemExit('usage: runtime.py PREFIX | prepare-game CONTENT DESTINATION | persist-directories GAME STATE [DIRECTORY ...] | apply-settings PREFIX GAME SETTINGS')
