"""Trusted fixed-model preload, before user bytes enter the sandbox."""
import hashlib
from io import BytesIO
import os
from pathlib import Path

from app.domain.documents.ocr_contracts import MODEL_HASHES, MODEL_SETTINGS

_engine = None


def get_runtime():
    global _engine
    if _engine is not None:
        return _engine
    # The isolated child sets these before importing any native dependency.
    for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
                'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS'):
        os.environ[key] = '1'
    import cv2
    import numpy as np
    import rapidocr
    from rapidocr import RapidOCR
    from PIL import Image
    import pypdfium2 as pdfium

    cv2.setNumThreads(1)
    Image.init()
    root = Path(rapidocr.__file__).parent / 'models'
    params = {'EngineConfig.onnxruntime.intra_op_num_threads': 1,
              'EngineConfig.onnxruntime.inter_op_num_threads': 1,
              'Global.log_level': 'critical', 'Global.text_score': 0.0}
    for stage, name in [('Det', 'PP-OCRv6_det_small.onnx'), ('Rec', 'PP-OCRv6_rec_small.onnx'),
                        ('Cls', 'ch_ppocr_mobile_v2.0_cls_mobile.onnx')]:
        path = root / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_HASHES[name]:
            raise ValueError('Unexpected installed OCR model')
        params[f'{stage}.model_path'] = str(path)
    engine = RapidOCR(params=params)
    # RapidOCR lazy-loads models; force all three even if the warmup has no boxes.
    engine._load_det_model(); engine._load_cls_model(); engine._load_rec_model()
    dictionary = engine.text_rec.session.session.get_modelmeta().custom_metadata_map['character']
    if hashlib.sha256(dictionary.encode('utf-8')).hexdigest() != MODEL_SETTINGS['dictionary_sha256']:
        raise ValueError('Unexpected embedded OCR dictionary')
    for model in (engine.text_det, engine.text_cls, engine.text_rec):
        session = model.session.session
        options = session.get_session_options()
        if session.get_providers() != ['CPUExecutionProvider'] or options.intra_op_num_threads != 1 or options.inter_op_num_threads != 1:
            raise ValueError('Unexpected OCR execution provider or threads')
    sample = np.full((240, 640, 3), 255, np.uint8)
    cv2.putText(sample, 'Warmup 123', (15, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 0), 2)
    output = engine(sample)
    if not output.txts:
        raise ValueError('OCR warmup did not exercise recognition')
    for fmt in ('PNG', 'JPEG'):
        buffer = BytesIO()
        Image.fromarray(sample).save(buffer, format=fmt)
        with Image.open(BytesIO(buffer.getvalue())) as image:
            image.convert('RGB').load()
    # Exercise PDFium memory input, rendering and JPEG output before isolation.
    pdf = pdfium.PdfDocument.new()
    page = pdf.new_page(100, 100)
    bitmap = page.render(scale=1)
    bitmap.to_pil().load(); bitmap.close()
    buffer = BytesIO(); pdf.save(buffer); page.close(); pdf.close()
    pdf = pdfium.PdfDocument(buffer.getvalue()); page = pdf[0]
    bitmap = page.render(scale=200 / 72); bitmap.to_pil().load()
    bitmap.get_posconv(page).to_page(0, 0)
    bitmap.close(); page.close(); pdf.close()
    _engine = engine
    return engine
