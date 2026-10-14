import subprocess
import sys

import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def test_contract_is_available_without_native_runtime():
    from app.domain.documents import ocr_contracts as c
    assert c.OCR_SETTINGS['ocr']['max_selected_pages'] == 10
    check = subprocess.run([sys.executable, '-c', "import sys; from app.domain.documents import ocr_contracts; assert not {'rapidocr','onnxruntime','cv2','pypdfium2'} & set(sys.modules)"], capture_output=True)
    assert check.returncode == 0, check.stderr
    assert c.OCR_SETTINGS['process']['timeout_seconds'] == 180


def test_text_is_strict_and_always_unreviewed():
    from app.domain.documents.ocr_contracts import OcrText
    value = dict(id='p1-t1', text='研究 12 mg', score=0.9,
                 polygon=[[0., 0.], [40., 0.], [40., 20.], [0., 20.]],
                 source=dict(page_number=1, polygon=[[0., 0.], [40., 0.], [40., 20.], [0., 20.]],
                             coordinate_system='image_pixels_top_left', label='第1页'))
    assert OcrText(**value).review_status == 'unreviewed'
    for key, bad in [('score', float('nan')), ('review_status', 'confirmed'), ('polygon', [[0., 0.]])]:
        with pytest.raises(ValidationError):
            OcrText(**(value | {key: bad}))
