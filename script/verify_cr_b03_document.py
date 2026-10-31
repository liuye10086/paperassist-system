"""Inspect a retained DOCX through the exact local PDF renderer, offline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'script/.runtime/client-requirements-b03'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--docx',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();source=args.docx.resolve();output=args.output.resolve()
    if not source.is_relative_to(RUNTIME) or not output.is_relative_to(RUNTIME) or source.suffix!='.docx':raise ValueError('Only retained B03 documents allowed')
    output.mkdir(parents=True,exist_ok=True)
    target=output/'analysis.pdf'
    if not target.exists():
        state=json.loads((RUNTIME/'state.json').read_text(encoding='utf-8'))
        image='pa-test-'+state['source_schema'][8:]+'-pdf-renderer:local'
        fonts=json.loads((ROOT/'backend/app/adapters/pdf_renderer_lock.json').read_text(encoding='utf-8'))['fonts']
        argv=['docker','run','--rm','-i','--network','none','--read-only','--memory','2g','--cpus','1','--tmpfs','/tmp:rw,nosuid,nodev,size=512m',
            '--mount',f'type=bind,source={source},target=/input.docx,readonly','--mount',f'type=bind,source={output},target=/output']
        for name in fonts:argv+=['--mount',f'type=bind,source={Path(os.environ["WINDIR"])/"Fonts"/name},target=/usr/local/share/fonts/paperassist/{name},readonly']
        argv+=['--entrypoint','python',image,'-c',"from pathlib import Path;import renderer;renderer.verify_environment();Path('/output/analysis.pdf').write_bytes(renderer.convert(Path('/input.docx').read_bytes()))"]
        completed=subprocess.run(argv,capture_output=True,timeout=105)
        (output/'renderer.stderr.txt').write_bytes(completed.stderr)
        if completed.returncode:raise RuntimeError('Document rendering failed; retained stderr')
    import pypdfium2 as pdfium
    pdf=pdfium.PdfDocument(target);pages=[]
    for i,page in enumerate(pdf):
        path=output/f'page-{i+1:02d}.png';image=page.render(scale=1.5).to_pil();image.save(path)
        text=page.get_textpage().get_text_range();(output/f'page-{i+1:02d}.txt').write_text(text,encoding='utf-8')
        pages.append(dict(page=i+1,width=page.get_width(),height=page.get_height(),text_characters=len(text),image=str(path)))
        page.close()
    pdf.close()
    receipt=dict(source=str(source),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),pdf_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        pages=pages,renderer='existing isolated LibreOffice locked image',network='none',visual_review='pending')
    (output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pages':len(pages),'output':str(output)}))


if __name__=='__main__':main()
