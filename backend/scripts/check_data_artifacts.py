"""Verify retained transit artifacts locally, without network requests or API keys."""
import argparse
import hashlib
import json
from pathlib import Path

FILES=('catalog.json','stations.json','geometry.json','bus/catalog.json','bus/geometry.json','schedules/manifest.json')
FEEDS={'subway','bx','b','m','q','si','busco'}


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def json_record(path):
    # Git/Windows may change CRLF checkout endings without changing the JSON data.
    content=Path(path).read_text(encoding='utf-8').encode('utf-8')
    return {'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}


def inventory(root):
    data={name:read(root/name) for name in FILES}
    subway=data['catalog.json'];bus=data['bus/catalog.json'];schedules=data['schedules/manifest.json']
    if not subway['stations'] or subway['stations']!=data['stations.json']:
        raise ValueError('Station array mismatch or empty catalog')
    for catalog,geometry in [(subway,data['geometry.json']),(bus,data['bus/geometry.json'])]:
        if catalog['metadata']!=geometry['metadata'] or geometry.get('type')!='FeatureCollection' or not geometry['features']:
            raise ValueError('Geometry provenance mismatch or missing features')
    if set(schedules['feeds'])!=FEEDS:raise ValueError('Schedule manifest must cover all seven feeds')
    if schedules['bus_discovery_snapshot_sha256']!=bus['metadata']['snapshot_sha256']:
        raise ValueError('Schedule crosswalk and bus snapshot mismatch')
    if schedules['feeds']['subway']['source_sha256']!=subway['metadata']['sha256']:
        raise ValueError('Subway catalog and schedule source mismatch')
    return {'schema_version':1,'json_checksum_format':'UTF-8 with line endings normalized to LF; other formatting retained',
            'files':{name:json_record(root/name) for name in FILES},
            'subway_import':subway['metadata'],'bus_import':bus['metadata'],
            'schedule_imported_at':schedules['imported_at']}


def verify(root, *, schedules=False, inputs=None, expected=None):
    lock=expected if expected is not None else read(root/'data-manifest.json');actual=inventory(root)
    if lock!=actual:raise ValueError('Data manifest does not match artifacts; review changes before refreshing it')
    manifest=read(root/'schedules/manifest.json')
    if schedules:
        for feed,result in manifest['feeds'].items():
            if result['artifact']!=feed+'.sqlite.gz':raise ValueError('Unexpected schedule artifact name')
            if sha256(root/'schedules'/result['artifact'])!=result['artifact_sha256']:
                raise ValueError('Schedule artifact checksum mismatch: '+feed)
    if inputs:
        source_manifest=read(inputs/'inputs-manifest.json')
        allowed={'gtfs_'+feed+'.zip' for feed in FEEDS}|{'bus-discovery.json'}
        if set(source_manifest['files'])!=allowed:raise ValueError('Unexpected offline input inventory')
        for name,digest in source_manifest['files'].items():
            if sha256(inputs/name)!=digest:raise ValueError('Offline input checksum mismatch: '+name)
        for feed,result in manifest['feeds'].items():
            if sha256(inputs/('gtfs_'+feed+'.zip'))!=result['source_sha256']:
                raise ValueError('Offline GTFS does not match pinned source: '+feed)
        snapshot=read(inputs/'bus-discovery.json')
        canonical=json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
        if hashlib.sha256(canonical).hexdigest()!=actual['bus_import']['snapshot_sha256']:
            raise ValueError('Offline bus snapshot mismatch')
    return actual


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=Path,default=Path(__file__).resolve().parents[1]/'app/data/generated')
    parser.add_argument('--schedules',action='store_true',help='Also verify the large local compressed schedule databases')
    parser.add_argument('--inputs-dir',type=Path,help='Verify an extracted offline source bundle')
    parser.add_argument('--write-manifest',action='store_true',help='Record a reviewed matching data set after an intentional refresh')
    args=parser.parse_args()
    try:
        if args.write_manifest:
            value=inventory(args.data_dir)
            verify(args.data_dir,schedules=args.schedules,inputs=args.inputs_dir,expected=value)
            (args.data_dir/'data-manifest.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
        else:
            verify(args.data_dir,schedules=args.schedules,inputs=args.inputs_dir)
    except (ValueError,KeyError,TypeError,OSError) as error:
        print('Artifact verification failed: '+str(error));return 1
    print('Artifact inventory, checksums and source provenance verified'+('; local schedules verified' if args.schedules else '')+'.')
    return 0


if __name__=='__main__':raise SystemExit(main())
