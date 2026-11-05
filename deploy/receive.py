#!/usr/bin/python3
"""Forced SSH command: accepts only a small, whitelisted static release."""
import fcntl
import gzip
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

BASE = Path('/var/www/saoke')
FILES = {'index.html', 'data.json', 'version.txt'}
LIMIT = 5 * 1024 * 1024


def activate(release):
    temporary = BASE / '.current-next'
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(release)
    temporary.replace(BASE / 'current')


def deploy():
    match = re.fullmatch(r'deploy ([0-9a-f]{40})', os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    if not match:
        raise ValueError('Only deploy <commit SHA> is allowed')
    revision = match.group(1)
    archive = sys.stdin.buffer.read(LIMIT + 1)
    if len(archive) > LIMIT:
        raise ValueError('Archive exceeds 5 MiB')

    # Never extract paths from an untrusted archive. Read only exact allowed names.
    with gzip.GzipFile(fileobj=io.BytesIO(archive)) as compressed:
        unpacked = compressed.read(LIMIT + 1)
    if len(unpacked) > LIMIT:
        raise ValueError('Uncompressed archive exceeds 5 MiB')
    with tarfile.open(fileobj=io.BytesIO(unpacked), mode='r:') as tar:
        members = tar.getmembers()
        if len(members) != len(FILES) or {m.name for m in members} != FILES:
            raise ValueError('Archive must contain only index.html, data.json and version.txt')
        if any(not m.isfile() or m.size > LIMIT for m in members):
            raise ValueError('Invalid archive entry')
        payloads = {m.name: tar.extractfile(m).read() for m in members}
    if payloads['version.txt'].decode().strip() != revision:
        raise ValueError('Commit SHA does not match release')
    if b'<!doctype html>' not in payloads['index.html'].lower():
        raise ValueError('Invalid index.html')
    data = json.loads(payloads['data.json'])
    expected = {'meta': {}, 'balance': '0.00', 'cashback': '0',
                'statement': {}, 'cards': [], 'txns': []}
    if data != expected:
        raise ValueError('Only empty deployment data is permitted')

    releases = BASE / 'releases'
    releases.mkdir(exist_ok=True)
    with (BASE / '.deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        release = Path(tempfile.mkdtemp(prefix=revision + '-', dir=releases))
        release.chmod(0o755)
        previous = (BASE / 'current').resolve() if (BASE / 'current').exists() else None
        try:
            for name, content in payloads.items():
                target = release / name
                target.write_bytes(content)
                target.chmod(0o644)
            activate(release)
            # Verify the actual Nginx HTTPS vhost before accepting this deployment.
            result = subprocess.run([
                'curl', '--fail', '--silent', '--show-error', '--max-time', '15',
                '--retry', '2', '--resolve', 'sk.zenify.cx:443:127.0.0.1',
                'https://sk.zenify.cx/version.txt',
            ], check=True, capture_output=True, text=True)
            if result.stdout.strip() != revision:
                raise ValueError('HTTPS health check returned an unexpected release')
        except Exception:
            if previous is not None:
                activate(previous)
            else:
                (BASE / 'current').unlink(missing_ok=True)
            shutil.rmtree(release)
            raise

        # Retain the five newest releases for manual rollback; the app stores no data here.
        history = sorted((p for p in releases.iterdir() if p.is_dir()),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        for old in history[5:]:
            if old != release and old != previous:
                shutil.rmtree(old)
    print(f'Deployed {revision} to https://sk.zenify.cx', flush=True)


if __name__ == '__main__':
    try:
        deploy()
    except Exception as error:
        print(f'Deployment failed: {error}', file=sys.stderr)
        raise SystemExit(1)
