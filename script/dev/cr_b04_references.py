"""Fetch a fixed public EBI GO release; never sends customer identifiers."""
import hashlib
import gzip
import re
import json
from pathlib import Path
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
CACHE=ROOT/'script/.runtime/client-requirements-b04/references/ebi-goex-2026-06-16'
BASE='https://ftp.ebi.ac.uk/pub/contrib/goa/goex/releases/2026-06-16/'
FILES={'go-basic.obo':'ontology/go-basic.obo','HUMAN-uniprot.gaf.gz':'uniprot-centric/gaf/HUMAN-uniprot.gaf.gz',
       'HUMAN-uniprot.gpi.gz':'uniprot-centric/gpi/HUMAN-uniprot.gpi.gz'}


def fetch():
    CACHE.mkdir(parents=True,exist_ok=True)
    for filename,relative in FILES.items():
        path=CACHE/filename;receipt=path.with_name(filename+'.download.json')
        if path.exists():
            saved=json.loads(receipt.read_text());assert hashlib.sha256(path.read_bytes()).hexdigest()==saved['sha256'];print('cached',filename,flush=True);continue
        url=BASE+relative;partial=path.with_name(filename+'.'+str(time.time_ns())+'.partial')
        digest=hashlib.sha256();size=0
        try:
            with urllib.request.urlopen(url,timeout=600) as response,partial.open('xb') as target:
                headers=dict(response.headers);final=response.url
                while chunk:=response.read(1024**2):
                    size+=len(chunk)
                    if size>128*1024**2:raise ValueError('Public reference exceeds declared download budget')
                    digest.update(chunk);target.write(chunk)
            if headers.get('Content-Length') and size!=int(headers['Content-Length']):raise ValueError('Download size mismatch')
            if not size:raise ValueError('Empty public reference')
            partial.replace(path)
            receipt.write_text(json.dumps(dict(url=url,final_url=final,release='2026-06-16',provider='EMBL-EBI GO exchange archive',
                headers=headers,size_bytes=size,sha256=digest.hexdigest(),retrieved_at=time.time(),customer_data_sent=False),indent=2),encoding='utf-8')
            print('fetched',filename,size,digest.hexdigest(),flush=True)
        except Exception as exc:
            partial.with_name(partial.name+'.failure.json').write_text(json.dumps(dict(url=url,error_type=type(exc).__name__,message=str(exc),bytes_received=size)),encoding='utf-8')
            raise


def mapping():
    path=CACHE/'HUMAN-uniprot.gpi.gz';target=CACHE/'ensembl-to-uniprot.tsv';receipt=CACHE/'mapping-derivation.json'
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    if target.exists():
        saved=json.loads(receipt.read_text(encoding='utf-8'))
        assert saved['input_sha256']==sha and saved['output_sha256']==hashlib.sha256(target.read_bytes()).hexdigest()
        return
    pairs=set();missing=0;version=None;header=[];other_namespaces={}
    with gzip.open(path,'rt',encoding='utf-8') as stream:
        for number,line in enumerate(stream,1):
            if line.startswith('!'):
                if line.startswith('!gpi-version:'):version=line.split(':',1)[1].strip()
                header.append(line.rstrip());continue
            if not line.strip():continue
            if version!='2.0':raise ValueError('Explicit GPI 2.0 column contract required')
            cells=line.rstrip('\r\n').split('\t')
            if len(cells)!=11 or cells[5]!='NCBITaxon:9606':
                raise ValueError('Fixed GPI human identity/shape changed')
            if not cells[0].startswith('UniProtKB:'):
                namespace=cells[0].split(':',1)[0];other_namespaces[namespace]=other_namespaces.get(namespace,0)+1;continue
            protein=cells[0].removeprefix('UniProtKB:')
            genes=[item.removeprefix('Ensembl:') for item in cells[9].split('|') if re.fullmatch(r'Ensembl:ENSG\d+(?:\.\d+)?',item)]
            if not genes:missing+=1
            for gene in genes:pairs.add((gene,protein))
    if not pairs:raise ValueError('No explicit Ensembl gene cross-references; do not infer symbols')
    content=('source_id\ttarget_id\n'+''.join(g+'\t'+p+'\n' for g,p in sorted(pairs))).encode()
    target.write_bytes(content)
    receipt.write_text(json.dumps(dict(input_file=path.name,input_sha256=sha,output_sha256=hashlib.sha256(content).hexdigest(),
        source_column='GPI 2.0 column 10 explicit Ensembl:ENSG gene DB xref',target_column='GPI 2.0 column 1 UniProtKB accession',
        namespace_conversion='Version stripping must be explicitly enabled during resource import; original versioned IDs retained here',
        gene_protein_pairs=len(pairs),entities_without_explicit_gene_xref=missing,excluded_entity_namespaces=other_namespaces,gpi_header=header,customer_ids_sent=False),indent=2),encoding='utf-8')
    print('explicit mapping',len(pairs),'pairs',flush=True)


def namespace_slice():
    """Explicit protein namespace subset; retain full official source and hashes."""
    source=CACHE/'HUMAN-uniprot.gaf.gz';target=CACHE/'HUMAN-UniProtKB-only.gaf.gz';receipt=CACHE/'gaf-namespace-slice.json'
    sha=hashlib.sha256(source.read_bytes()).hexdigest()
    if target.exists():
        saved=json.loads(receipt.read_text(encoding='utf-8'))
        assert saved['input_sha256']==sha and saved['output_sha256']==hashlib.sha256(target.read_bytes()).hexdigest();return
    accepted=0;excluded={};headers=[]
    with gzip.open(source,'rt',encoding='utf-8') as incoming,target.open('xb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as out:
        for line in incoming:
            if line.startswith('!'):
                headers.append(line.rstrip());out.write(line.encode());continue
            if not line.strip():continue
            cells=line.rstrip('\r\n').split('\t')
            if len(cells)!=17:raise ValueError('GAF 2.2 shape changed')
            if cells[0]!='UniProtKB' or cells[12].split('|')[0]!='taxon:9606':
                reason=cells[0]+':'+cells[12];excluded[reason]=excluded.get(reason,0)+1;continue
            accepted+=1;out.write(line.encode())
    receipt.write_text(json.dumps(dict(input_file=source.name,input_sha256=sha,output_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        filter='GAF DB exactly UniProtKB and first taxon exactly taxon:9606; no evidence/term filtering at this preparation step',
        accepted_annotations=accepted,excluded_namespace_or_taxon=excluded,original_header=headers,original_retained=True),indent=2),encoding='utf-8')
    print('explicit GAF namespace slice',accepted,'annotations',flush=True)


if __name__=='__main__':
    fetch();mapping();namespace_slice()
