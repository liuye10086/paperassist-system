"""Immutable, bounded packages with exact member hashes and no mutable links."""
import hashlib
import io
import json
import re
import zipfile

MAX_MEMBERS=256
MAX_BYTES=256*1024*1024


def make_package(files,identity):
    if len(files)+2>MAX_MEMBERS:raise ValueError('ZIP member limit exceeded; split the report')
    if set(files)&{'manifest.json','SHA256SUMS.txt'}:raise ValueError('Reserved package name')
    for name,content in files.items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*',name) or any(p in ('.','..') for p in name.split('/')):
            raise ValueError('Unsafe package member name')
        if type(content) is not bytes:raise ValueError('Package members must be fixed bytes')
    manifest={'schema_version':1,'identity':identity,'members':[
        {'name':name,'size_bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()} for name,content in sorted(files.items())]}
    manifest_bytes=json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8')
    hashes=''.join(m['sha256']+'  '+m['name']+'\n' for m in manifest['members'])
    hashes+=hashlib.sha256(manifest_bytes).hexdigest()+'  manifest.json\n'
    contents={**files,'manifest.json':manifest_bytes,'SHA256SUMS.txt':hashes.encode('utf-8')}
    if sum(map(len,contents.values()))>MAX_BYTES:raise ValueError('ZIP byte limit exceeded; split the report')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for name,content in sorted(contents.items()):
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            archive.writestr(info,content)
    result=output.getvalue()
    if len(result)>MAX_BYTES:raise ValueError('ZIP byte limit exceeded; split the report')
    return result,manifest


def verify_package(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        infos=archive.infolist()
        if len(infos)>MAX_MEMBERS or len(set(i.filename for i in infos))!=len(infos) or sum(i.file_size for i in infos)>MAX_BYTES:
            raise ValueError('Invalid package bounds')
        manifest=json.loads(archive.read('manifest.json'))
        expected={m['name'] for m in manifest['members']}|{'manifest.json','SHA256SUMS.txt'}
        if set(archive.namelist())!=expected:raise ValueError('Package member mismatch')
        for member in manifest['members']:
            raw=archive.read(member['name'])
            if len(raw)!=member['size_bytes'] or hashlib.sha256(raw).hexdigest()!=member['sha256']:raise ValueError('Package member hash mismatch')
        return manifest
