"""Real engine -> public serializer response, also consumed by the UI test."""
from io import BytesIO
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from docx import Document
from app.adapters.document_layout import apply_layout, catalog_docx
from app.core.errors import error_response
from app.core.exceptions import StorageError
from app.domain.document_layout import LayoutOptions


def response_body(case='invalid'):
    doc = Document()
    doc.add_paragraph('Original source anchor')
    stream = BytesIO()
    doc.save(stream)
    source = stream.getvalue()
    anchor = catalog_docx(source)['anchors'][0]['id']
    value = {'formulas': [{'id': 'badFormula', 'anchor_id': anchor,
                          'expression': r'\unsupported{x}' if case == 'invalid' else 'x' * 100}]}
    if case == 'target':
        value = {'references': [{'anchor_id': anchor, 'target_id': 'absent', 'kind': 'page'}]}
    elif case == 'pagination':
        value = {'pagination': {'mode': 'roman_front', 'body_anchor_id': anchor}}
    elif case == 'toc':
        value = {'toc': {'depth': 1}}
    try:
        apply_layout(source, LayoutOptions.model_validate(value), language='en')
    except StorageError as exc:
        return json.loads(error_response(exc.status, exc.code, str(exc), exc.params).body)
    raise AssertionError('fixture must fail through the product engine')


if __name__ == '__main__':
    print(json.dumps(response_body(sys.argv[1] if len(sys.argv) > 1 else 'invalid')))
