"""Run from backend: python scripts/import_mta_gtfs.py [--zip local.zip]."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from app.services.mta_client import STATIC_URL
from app.services.static_gtfs import build_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, help='Use a downloaded official GTFS ZIP')
    parser.add_argument('--output', type=Path, default=Path('app/data/generated'))
    args = parser.parse_args()
    if args.zip:
        content = args.zip.read_bytes()
    else:
        response = requests.get(STATIC_URL, timeout=(5, 120))
        response.raise_for_status()
        content = response.content
    catalog = build_catalog(content)
    catalog['metadata'] = {'source_url': STATIC_URL, 'imported_at': datetime.now(timezone.utc).isoformat(),
                           'sha256': hashlib.sha256(content).hexdigest(),
                           'input_file': args.zip.name if args.zip else None}
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in [('catalog.json', catalog), ('stations.json', catalog['stations'])]:
        target = args.output / name
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(target)
    print(f"Imported {len(catalog['stations'])} parent stations into {args.output}")


if __name__ == '__main__':
    main()
