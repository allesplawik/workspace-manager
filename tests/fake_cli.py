"""Executable provider fixtures; never contact an AI service."""

import sys
from pathlib import Path

STUB = r"""
import json, os, signal, sys, time
from pathlib import Path
name = Path(sys.argv[0]).name
if '--help' in sys.argv:
    if name == 'codex':
        print('--last' if 'resume' in sys.argv else 'Commands:\n  resume Native picker')
    else:
        print('--resume --continue')
    sys.exit(0)
record = {'provider': name, 'argv': sys.argv[1:], 'cwd': os.getcwd(), 'tty': os.isatty(0)}
print('\x1b[31m' + json.dumps(record) + '\x1b[0m', flush=True)
log = os.environ.get('WM_STUB_LOG')
if log:
    destination = Path(log) / (name + '.json')
    destination.write_text(json.dumps(record))
    def resized(signum, frame):
        (Path(log) / (name + '.resize')).write_text(str(os.get_terminal_size(0)))
    signal.signal(signal.SIGWINCH, resized)
if os.environ.get('WM_STUB_HOLD') == '1':
    while True:
        data = sys.stdin.readline()
        if data.strip() == 'exit' or not data:
            break
        print('echo:' + data.strip(), flush=True)
"""


def make_cli(directory: Path, name: str) -> Path:
    path = directory / name
    path.write_text(f"#!{sys.executable}\n" + STUB)
    path.chmod(0o700)
    return path
