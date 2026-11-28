"""Online B13–B16 check. Records source-derived summaries, never credentials."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    app = create_app({'TRANSIT_MODE':'live'})
    client = app.test_client()
    results = []
    for path in ('/api/service-status?mode=subway', '/api/service-status?mode=bus',
                 '/api/stations/R20/equipment', '/api/stations/L06/equipment'):
        response = client.get(path, headers={'Origin':app.config['FRONTEND_ORIGIN']})
        body = response.get_json()
        rows = body.get('statuses',body.get('equipment',[]))
        item = {'path':path,'http_status':response.status_code,'source':body.get('source'),
                'updated_at':body.get('updated_at'),'count':len(rows),
                'status_counts':{status:sum(row['status']==status for row in rows)
                                 for status in sorted({row['status'] for row in rows})},
                'coverage':body.get('coverage'),
                'cors_origin':response.headers.get('Access-Control-Allow-Origin'),
                'passed':response.status_code==200 and body.get('source')=='mta'}
        if 'error' in body:
            item['error'] = body['error']
        results.append(item)
        print(json.dumps(item),flush=True)
    report = {'checked_at_utc':datetime.now(timezone.utc).isoformat(),
              'equipment_timestamp_basis':'Official HTTP Date; upstream payload has no publication or per-asset change timestamp',
              'passed':all(row['passed'] for row in results),'results':results}
    if args.output:
        args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
