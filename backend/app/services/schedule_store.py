"""Open the retained per-feed schedule databases at runtime (Y15).

The tracked manifest pins each feed's gzip artifact by SHA-256. On first use a
feed is checked against that hash and decompressed once next to the artifact as
`<feed>.<sha-prefix>.sqlite` (ignored by git), then opened read-only. A missing,
changed or unreadable artifact is reported as unavailable, never replaced by
made-up data. Set SCHEDULE_DIR to serve the files from another directory.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
from threading import Lock

DEFAULT_DIR = Path(__file__).parents[1] / 'data' / 'generated' / 'schedules'
CHUNK = 1 << 20


class ScheduleUnavailable(RuntimeError):
    """Schedule data for a feed cannot be served."""


class ScheduleStore:
    def __init__(self, directory=None):
        self.directory = Path(directory or os.getenv('SCHEDULE_DIR') or DEFAULT_DIR)
        self._manifest, self._paths, self._lock = None, {}, Lock()

    @property
    def manifest(self):
        with self._lock:
            if self._manifest is None:
                try:
                    manifest = json.loads((self.directory / 'manifest.json').read_text(encoding='utf-8'))
                    if not isinstance(manifest.get('feeds'), dict) or not manifest['feeds'] or not manifest.get('imported_at'):
                        raise ValueError('Incomplete schedule manifest')
                except (OSError, ValueError) as error:
                    raise ScheduleUnavailable('Schedule manifest is unavailable') from error
                self._manifest = manifest
            return self._manifest

    @property
    def updated_at(self):
        return self.manifest['imported_at']

    def feeds(self, mode):
        names = list(self.manifest['feeds'])
        return ['subway'] if mode == 'subway' and 'subway' in names else [n for n in names if n != 'subway'] if mode == 'bus' else []

    def path(self, feed):
        entry = self.manifest['feeds'].get(feed)
        if not entry:
            raise ScheduleUnavailable(f'Unknown schedule feed {feed}')
        with self._lock:
            if feed in self._paths:
                return self._paths[feed]
            try:
                expected = entry['artifact_sha256']
                artifact = self.directory / entry['artifact']
                target = self.directory / f'{feed}.{expected[:16]}.sqlite'
                if not target.exists():
                    digest = hashlib.sha256()
                    with artifact.open('rb') as source:
                        for chunk in iter(lambda: source.read(CHUNK), b''):
                            digest.update(chunk)
                    if digest.hexdigest() != expected:
                        raise ValueError('Schedule artifact does not match the manifest')
                    partial = target.with_suffix('.tmp')
                    with gzip.open(artifact, 'rb') as source, partial.open('wb') as destination:
                        shutil.copyfileobj(source, destination, CHUNK)
                    os.replace(partial, target)
            except (OSError, KeyError, ValueError, EOFError) as error:
                raise ScheduleUnavailable(f'Schedule feed {feed} is unavailable') from error
            self._paths[feed] = target
            return target

    def connect(self, feed):
        try:
            connection = sqlite3.connect(self.path(feed).as_uri() + '?mode=ro', uri=True)
            connection.execute('SELECT 1 FROM stop_times LIMIT 1')
            return connection
        except sqlite3.Error as error:
            raise ScheduleUnavailable(f'Schedule feed {feed} is unavailable') from error
