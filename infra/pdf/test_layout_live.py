"""Opt-in real isolated renderer regression, no model or business DB access.

PAPERASSIST_LAYOUT_LIVE=1 PAPERASSIST_PDF_RENDERER_URL=<loopback|internal>
python -m pytest infra/pdf/test_layout_live.py -q
"""
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from zipfile import ZipFile

from docx import Document
from lxml import etree as E
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from app.adapters.document_layout import catalog_docx, prepare_layout_docx
from app.adapters.pdf_renderer import update_layout_fields
from app.domain.document_layout import LayoutOptions

pytestmark = pytest.mark.skipif(os.environ.get('PAPERASSIST_LAYOUT_LIVE') != '1',
                                reason='requires explicitly selected isolated local renderer')


def test_actual_office_word_toc_math_fields(tmp_path):
    doc = Document()
    doc.add_paragraph('Front matter')
    doc.add_heading('Exact body heading', 1)
    doc.add_paragraph('Scientific body retained.')
    doc.add_heading('Second heading', 1)
    stream = BytesIO()
    doc.save(stream)
    content = stream.getvalue()
    anchors = catalog_docx(content)['anchors']
    options = LayoutOptions.model_validate({
        'toc': {'depth': 2},
        'pagination': {'mode': 'roman_front', 'body_anchor_id': anchors[1]['id']},
        'formulas': [{'id': 'formula1', 'anchor_id': anchors[1]['id'], 'expression': r'\frac{a}{b}+\sqrt{x}+\alpha'}],
        'references': [{'anchor_id': anchors[-1]['id'], 'target_id': anchors[1]['id'], 'kind': 'page', 'prefix': 'BODY_PAGE='},
                       {'anchor_id': anchors[-1]['id'], 'target_id': 'formula:formula1', 'kind': 'number', 'prefix': 'EQUATION='}],
    })
    result = prepare_layout_docx(content, options, language='en')
    (tmp_path / 'layout.docx').write_bytes(result)
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
          'm': 'http://schemas.openxmlformats.org/officeDocument/2006/math'}
    with ZipFile(BytesIO(result)) as package:
        root = E.fromstring(package.read('word/document.xml'))
        assert len(root.xpath('//m:oMath', namespaces=ns)) == 1
        assert len(root.xpath('//w:instrText[contains(text(),"TOC")]', namespaces=ns)) == 1
        meta = json.loads(E.fromstring(package.read('customXml/paperassist-layout.xml')).text)
        assert meta['cache_status'] == 'complete'
    # A second actual Writer import must not duplicate our TOC.
    cache = update_layout_fields(result)
    assert sum('Exact body heading' in line for line in cache['toc_lines']) == 1
    assert any("Second heading" in line for line in cache["toc_lines"])
