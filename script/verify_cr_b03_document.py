"""Inspect only an already retained B03 PDF; PDF generation has been retired."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'script/.runtime/client-requirements-b03'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--docx',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=args.docx.resolve();output=args.output.resolve()
    if not source.is_relative_to(RUNTIME) or not output.is_relative_to(RUNTIME) or source.suffix!='.docx':raise ValueError('Only retained B03 documents allowed')
    output.mkdir(parents=True,exist_ok=True)
    target=output/'analysis.pdf'
    if not target.exists():
        raise FileNotFoundError('No saved historical PDF; automatic PDF generation has been removed. Use Word for current document review.')
    import pypdfium2 as pdfium
    pdf=pdfium.PdfDocument(target);pages=[]
    for i,page in enumerate(pdf):
        path=output/f'page-{i+1:02d}.png';image=page.render(scale=1.5).to_pil();image.save(path)
        text=page.get_textpage().get_text_range();(output/f'page-{i+1:02d}.txt').write_text(text,encoding='utf-8')
        pages.append(dict(page=i+1,width=page.get_width(),height=page.get_height(),text_characters=len(text),image=str(path)))
        page.close()
    pdf.close()
    receipt=dict(source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),pdf_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        pages=pages,renderer='saved historical PDF; no renderer executed',network='none',visual_review='pending')
    (output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pages':len(pages),'output':str(output)}))


if __name__=='__main__':main()
