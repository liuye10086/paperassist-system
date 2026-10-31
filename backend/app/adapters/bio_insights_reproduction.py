"""Streaming, content-addressed ZIP assembly with no client-selected paths."""
import csv
import hashlib
import json
from pathlib import Path,PurePosixPath
import tempfile
import zipfile

from app.adapters.bio_insights_store import invalid
from app.domain.bioinformatics.contracts import canonical


def table_shape(path,fmt,*,header='declared'):
    if header not in ('declared','uninterpreted'):raise invalid()
    with Path(path).open('r',encoding='utf-8-sig',newline='') as stream:
        reader=csv.reader(stream,delimiter='\t' if fmt=='tsv' else ',',strict=True)
        columns=next(reader,None)
        if not columns or header=='declared' and len(columns)!=len(set(columns)):raise invalid()
        rows=1 if header=='uninterpreted' else 0
        for row in reader:
            if len(row)!=len(columns):raise invalid()
            rows+=1
            if rows>10000000:raise invalid('bio_insight_limit_exceeded',422)
    if header=='uninterpreted':return dict(format=fmt,header='uninterpreted',column_count=len(columns),records=rows)
    return dict(format=fmt,columns=columns,rows=rows)


class ReproductionArchive:
    def __init__(self):
        self.file=tempfile.TemporaryFile(mode='w+b')
        self.zip=zipfile.ZipFile(self.file,'w',compression=zipfile.ZIP_STORED,allowZip64=True)
        self.records={};self.total=0;self.closed=False

    @staticmethod
    def name(name):
        value=PurePosixPath(name)
        if not name or value.is_absolute() or any(part in ('.','..') for part in value.parts) or '\\' in name or ':' in name:
            raise invalid('bio_insight_source_conflict',422)
        return name

    def add_bytes(self,name,content):
        name=self.name(name);sha=hashlib.sha256(content).hexdigest()
        if name in self.records:
            if self.records[name]['sha256']!=sha:raise invalid()
            return self.records[name]
        self.total+=len(content)
        if self.total>2*1024**3:raise invalid('bio_insight_limit_exceeded',422)
        self.zip.writestr(name,content)
        record=dict(path=name,size_bytes=len(content),sha256=sha);self.records[name]=record;return record

    def add_json(self,name,value):return self.add_bytes(name,canonical(value))

    def add_reproduction_programs(self,app_root=None):
        root=Path(app_root) if app_root is not None else Path(__file__).resolve().parents[1]
        resources=root/'reproduction_assets/bio_insights'
        for name in ('reproduce.py','render_worker.py'):
            self.add_bytes(name,(resources/name).read_bytes())

    def add_file(self,name,path,expected,*,fmt=None,table_header='declared'):
        name=self.name(name);path=Path(path)
        if path.is_symlink() or not path.is_file() or path.stat().st_size!=expected['size_bytes'] or not 0<expected['size_bytes']<=268435456:raise invalid()
        if name in self.records:
            if any(self.records[name][key]!=expected[key] for key in ('sha256','size_bytes')):raise invalid()
            return self.records[name]
        self.total+=expected['size_bytes']
        if self.total>2*1024**3:raise invalid('bio_insight_limit_exceeded',422)
        sha=hashlib.sha256();size=0
        with path.open('rb') as source,self.zip.open(name,'w',force_zip64=True) as target:
            while chunk:=source.read(1024**2):target.write(chunk);sha.update(chunk);size+=len(chunk)
        if size!=expected['size_bytes'] or sha.hexdigest()!=expected['sha256']:raise invalid()
        record=dict(path=name,size_bytes=size,sha256=sha.hexdigest())
        if fmt in ('tsv','csv'):record['table']=table_shape(path,fmt,header=table_header)
        self.records[name]=record;return record

    def finish(self,package):
        package['files']=list(self.records.values());content=canonical(package)
        self.zip.writestr('package.json',content);self.zip.close();self.closed=True
        self.file.seek(0)
        return self.file,hashlib.sha256(content).hexdigest()

    def close(self):
        if not self.closed:self.zip.close()
        self.file.close()
