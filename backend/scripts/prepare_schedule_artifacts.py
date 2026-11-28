"""B22: install only schedules that match the reviewed manifest; never refresh transit sources.

Use --source-dir for existing Yuming-built artifacts, or --download-dir to rebuild
from the pinned official archives. A changed archive/hash stops the build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

BACKEND = Path(__file__).resolve().parents[1]
MANIFEST = BACKEND / 'app/data/generated/schedules/manifest.json'


def sha(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def verify(directory, manifest):
    for name, entry in manifest['feeds'].items():
        if entry['artifact'] != name + '.sqlite.gz':
            raise ValueError('Invalid artifact filename in reviewed manifest')
        path = directory / entry['artifact']
        if not path.is_file() or sha(path) != entry['artifact_sha256']:
            raise ValueError('Missing or mismatched reviewed schedule: ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path)
    parser.add_argument('--download-dir',type=Path)
    parser.add_argument('--output',type=Path,default=MANIFEST.parent)
    parser.add_argument('--check',action='store_true')
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if args.check:
        verify(args.output,manifest)
        print('All reviewed schedule artifacts verified.')
        return
    if args.source_dir and args.download_dir:
        parser.error('Choose source-dir or download-dir, not both')
    if not args.source_dir and not args.download_dir:
        parser.error('Provide --source-dir or --download-dir; no network download is implicit')
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        if args.source_dir:
            source = args.source_dir.resolve()
        else:
            source = stage / 'schedules'
            subprocess.run([sys.executable,str(BACKEND/'scripts/import_schedules.py'),
                '--from-manifest',str(MANIFEST),'--download-dir',str(args.download_dir.resolve()),
                '--output',str(source)],cwd=BACKEND,check=True)
        verify(source,manifest)
        # Verify the entire set before replacing any destination. Run before
        # starting/restarting Flask, not against an active ScheduleStore.
        args.output.mkdir(parents=True,exist_ok=True)
        for entry in manifest['feeds'].values():
            original, destination = source/entry['artifact'], args.output/entry['artifact']
            if original.resolve() != destination.resolve():
                staged = destination.with_suffix('.tmp')
                shutil.copyfile(original,staged)
                staged.replace(destination)
        if args.output.resolve() != MANIFEST.parent.resolve():
            (args.output/'manifest.json').write_bytes(MANIFEST.read_bytes())
    print('Installed all reviewed schedules; tracked manifest unchanged.')


if __name__ == '__main__':
    main()
