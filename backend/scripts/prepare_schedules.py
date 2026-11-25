"""Verify and decompress every retained schedule feed before serving (Y15).

Run once after regenerating schedules or during a deployment build, so the first
/api/schedules request does not pay the decompression cost:

    .venv/bin/python scripts/prepare_schedules.py [--dir app/data/generated/schedules]
"""
import argparse
from contextlib import closing
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.schedule_store import ScheduleStore, ScheduleUnavailable  # noqa: E402
from app.services.service_calendar import feed_coverage  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--dir', help='Schedule directory (default: SCHEDULE_DIR or the generated schedules)')
    store = ScheduleStore(parser.parse_args().dir)
    failed = False
    for feed in store.manifest['feeds']:
        try:
            with closing(store.connect(feed)) as connection:
                first, last = feed_coverage(connection)
            print(f'{feed}: ready, service {first} to {last} ({store.path(feed).name})')
        except (ScheduleUnavailable, LookupError) as error:
            failed = True
            print(f'{feed}: UNAVAILABLE ({error})', file=sys.stderr)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
