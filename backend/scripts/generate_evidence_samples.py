"""Generate synthetic Step14 inputs in a NEW directory, without database access."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tests.helpers.evidence_samples import evidence_docx,evidence_pdf,evidence_xlsx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    target=Path(args.output).resolve()
    target.mkdir(parents=True,exist_ok=False)
    samples={'captions.docx':evidence_docx(),'captions.pdf':evidence_pdf(),
        'image-only.pdf':evidence_pdf(image_only=True),'lexical.xlsx':evidence_xlsx()}
    manifest={}
    for name,content in samples.items():
        (target/name).write_bytes(content)
        manifest[name]={'size_bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(str(target))
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
