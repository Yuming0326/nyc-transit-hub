"""Retain validated GTFS schedules from explicit local official archives."""
import argparse
from datetime import datetime, timezone
import json
import hashlib
import requests
from pathlib import Path
import shutil
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.services.schedule_import import retain_schedule

SOURCES = {'subway':'gtfs_subway.zip', 'bx':'gtfs_bx.zip', 'b':'gtfs_b.zip', 'm':'gtfs_m.zip',
           'q':'gtfs_q.zip', 'si':'gtfs_si.zip', 'busco':'gtfs_busco.zip'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--feed', action='append', help='Feed name=local.zip; names: '+','.join(SOURCES))
    parser.add_argument('--bus-catalog',type=Path,default=Path('app/data/generated/bus/catalog.json'))
    parser.add_argument('--output',type=Path,default=Path('app/data/generated/schedules'))
    parser.add_argument('--from-manifest',type=Path,help='Download official archives pinned by an existing manifest')
    parser.add_argument('--download-dir',type=Path,help='Directory outside the repo for pinned archives')
    args=parser.parse_args()
    feeds={}
    if args.from_manifest:
        if args.feed or not args.download_dir:parser.error('Use --from-manifest with --download-dir and no --feed')
        pinned=json.loads(args.from_manifest.read_text(encoding='utf-8'))
        args.download_dir.mkdir(parents=True,exist_ok=True)
        for name,entry in pinned['feeds'].items():
            if name not in SOURCES:parser.error('Unsupported manifest feed')
            url='https://rrgtfsfeeds.s3.amazonaws.com/'+SOURCES[name]
            path=args.download_dir/SOURCES[name]
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['source_sha256']:
                response=requests.get(url,timeout=(5,120));response.raise_for_status()
                if hashlib.sha256(response.content).hexdigest()!=entry['source_sha256']:
                    raise ValueError('Official archive changed: review a new snapshot instead of silently replacing the pinned feed')
                path.write_bytes(response.content)
            feeds[name]=path
    elif not args.feed:parser.error('Provide --feed or --from-manifest')
    for value in args.feed or []:
        name,separator,path=value.partition('=')
        if not separator or name not in SOURCES or name in feeds:parser.error('Each --feed must identify one distinct supported feed')
        feeds[name]=Path(path)
    discovery=json.loads(args.bus_catalog.read_text(encoding='utf-8')) if set(feeds)-{'subway'} else None
    manifest={'schema_version':1,'imported_at':datetime.now(timezone.utc).isoformat(),
              'bus_discovery_snapshot_sha256':discovery['metadata']['snapshot_sha256'] if discovery else None,
              'id_scope':'(feed_id, source_id); entity_links explicitly maps public IDs', 'feeds':{}}
    with tempfile.TemporaryDirectory() as directory:
        stage=Path(directory)
        for name,path in sorted(feeds.items()):
            artifact=name+'.sqlite.gz'
            result=retain_schedule(path,stage/artifact,mode='subway' if name=='subway' else 'bus',discovery=discovery)
            result.update(source_url='https://rrgtfsfeeds.s3.amazonaws.com/'+SOURCES[name],artifact=artifact)
            manifest['feeds'][name]=result
            print(name+': '+json.dumps(result['counts'])+'; overnight rows: '+str(result['overnight_stop_times']),flush=True)
        if discovery:
            covered={r for name,result in manifest['feeds'].items() if name!='subway' for r in result['active_public_route_ids']}
            manifest['discovery_routes_without_schedule']=sorted({r['id'] for r in discovery['routes']}-covered)
        (stage/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        args.output.mkdir(parents=True,exist_ok=True)
        for path in sorted(stage.iterdir(),key=lambda p:(p.name=='manifest.json',p.name)):
            target=args.output/path.name;temporary=target.with_suffix('.tmp')
            shutil.copyfile(path,temporary);temporary.replace(target)
    print('Published validated schedule set; no runtime APIs enabled.')


if __name__=='__main__':main()
