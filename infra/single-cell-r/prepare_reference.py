"""Explicit build-time public-data preparation; never imported by the Worker."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

SOURCES={
    'monaco-logcounts.rds':('https://experimenthub.bioconductor.org/fetch/3512','e3b00cc5a067c30f4e0771bee0d55123b99792d6ec8a8f37c5402563c6bba456'),
    'monaco-coldata.rds':('https://experimenthub.bioconductor.org/fetch/3513','b0f2d858616c48e835ec79376732dac41ae0564708d3707b7b039a994fc3208b'),
    'hgnc_complete_set.txt':('https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/hgnc_complete_set.txt','d93ce6b22d01dc1e1ded28857246951d605ead47ed17ef973ad1142b1d13bed0'),
}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--rscript',default='/opt/paperassist-single-cell-r/bin/Rscript')
    args=parser.parse_args();args.source.mkdir(parents=True,exist_ok=True)
    for name,(url,expected) in SOURCES.items():
        path=args.source/name
        if not path.exists():urllib.request.urlretrieve(url,path)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('reference_source_checksum_mismatch:'+name)
    dest=args.output/'monaco_immune_1.0.0'
    subprocess.run([args.rscript,'--vanilla',str(Path(__file__).with_suffix('.R')),str(args.source),str(dest)],check=True)
    metadata=json.loads((dest/'prepared.json').read_text())
    metadata.update(reference_id='monaco_immune_1.0.0',version='1.0.0',species='Homo sapiens',species_taxon_id=9606,
        gene_id_type='ensembl_gene_id',source='celldex MonacoImmuneData legacy 1.0.0; ExperimentHub EH3496/EH3497; GEO GSE107011',
        license='celldex GPL-3; upstream publication CC-BY-4.0; HGNC mapping CC0-1.0',
        license_details={'celldex_package':'GPL-3','upstream_publication':'CC-BY-4.0','GEO_data':'public accession; no separate dataset license asserted','mapping':'CC0-1.0'},
        citation='Monaco et al. Cell Reports 26, 1627-1640.e7 (2019). doi:10.1016/j.celrep.2019.01.041',
        license_sources=['https://bioconductor.posit.co/packages/3.20/data/experiment/html/celldex.html','https://pmc.ncbi.nlm.nih.gov/articles/PMC6367568/','https://hgnc.genenames.org/about/license/'],
        source_files={name:dict(url=url,sha256=digest) for name,(url,digest) in SOURCES.items()},
        mapping_policy='exact_approved_HGNC_symbol_to_unique_Ensembl_gene_ID; drop_missing_and_duplicate_IDs; no_alias_inference',
        prepared_on='2026-11-05',sha256=hashlib.sha256((dest/'reference.rds').read_bytes()).hexdigest())
    (dest/'reference.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in metadata.items() if key!='gene_ids'},ensure_ascii=False))


if __name__=='__main__':main()
