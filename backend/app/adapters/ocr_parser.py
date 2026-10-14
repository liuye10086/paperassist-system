"""Bounded, local CPU OCR and previews. Native modules are loaded on demand."""
import base64
import hashlib
from io import BytesIO
import json
import math

from app.core.exceptions import StorageError
from app.domain.documents.ocr_contracts import (
    MODEL_SETTINGS, OCR_SETTINGS, PARSER_VERSION, PROCESS_SETTINGS, OcrSettings,
    OcrCounts, OcrDocument, OcrPage, OcrParseResult, OcrSource, OcrText, Image, Warning,
)


def fail(code, message='识别失败，请核对文件格式、大小和所选页。'):
    raise StorageError(code, message, 422)


def validate_inputs(content, filename, file_type, page_numbers, settings):
    try:
        if (type(settings) is not dict or set(settings) != {'ocr', 'process', 'models'}
                or settings['process'] != PROCESS_SETTINGS or settings['models'] != MODEL_SETTINGS
                or any(type(x) is not int for x in settings['process'].values())
                or type(settings['models'].get('threads')) is not int
                or type(settings['ocr']) is not dict or set(settings['ocr']) != set(OcrSettings.model_fields)):
            raise ValueError()
        limits = OcrSettings.model_validate(settings['ocr'])
        if type(content) is not bytes or type(filename) is not str or not 0 < len(filename) <= 1024:
            raise ValueError()
    except Exception:
        fail('parse_environment_unavailable', 'OCR识别设置无效。')
    if not content:
        fail('empty_file', '上传文件为空。')
    if len(content) > limits.max_upload_bytes:
        fail('file_too_large', '上传文件超过大小限制。')
    if (file_type not in ('pdf', 'png', 'jpeg') or type(file_type) is not str
            or type(page_numbers) is not list or not 1 <= len(page_numbers) <= limits.max_selected_pages
            or any(type(page) is not int or not 1 <= page <= limits.max_pages for page in page_numbers)
            or len(set(page_numbers)) != len(page_numbers)
            or (file_type != 'pdf' and page_numbers != [1])):
        fail('invalid_document', '所选页必须是1—10个唯一物理页；图片只能选择第1页。')
    return limits


def _image(content, file_type, limits):
    from PIL import Image as PillowImage, ImageOps, UnidentifiedImageError
    try:
        image = PillowImage.open(BytesIO(content))
        if image.format != {'png': 'PNG', 'jpeg': 'JPEG'}[file_type] or getattr(image, 'n_frames', 1) != 1:
            fail('invalid_document')
        width, height = image.size
        if width * height > limits.max_image_pixels:
            fail('document_too_large', '图片像素超过识别限制。')
        orientation = image.getexif().get(274, 1)
        # Coordinate edges (not pixel centres), inverse EXIF transform to the original image.
        mapping = {
            1: ([1., 0., 0., 0., 1., 0.], 0),
            2: ([-1., 0., float(width), 0., 1., 0.], 0),
            3: ([-1., 0., float(width), 0., -1., float(height)], 180),
            4: ([1., 0., 0., 0., -1., float(height)], 0),
            5: ([0., 1., 0., 1., 0., 0.], 90),
            6: ([0., 1., 0., -1., 0., float(height)], 90),
            7: ([0., -1., float(width), -1., 0., float(height)], 270),
            8: ([0., -1., float(width), 1., 0., 0.], 270),
        }
        affine, rotation = mapping.get(orientation, mapping[1])
        normalized = ImageOps.exif_transpose(image)
        # Alpha is composited on white before RGB recognition and JPEG preview.
        if normalized.mode in ('RGBA', 'LA') or 'transparency' in normalized.info:
            rgba = normalized.convert('RGBA')
            rgb = PillowImage.new('RGB', normalized.size, 'white')
            rgb.paste(rgba, mask=rgba.getchannel('A'))
        else:
            rgb = normalized.convert('RGB')
        image.close()
        return rgb, dict(rotation=rotation, source_width=float(width), source_height=float(height),
                         source_coordinate_system='image_pixels_top_left', pixel_to_source=affine,
                         transforms=[f'exif_orientation:{orientation}', 'rgb_white_background'])
    except (UnidentifiedImageError, OSError, ValueError, PillowImage.DecompressionBombError):
        fail('invalid_document')


def _map(polygon, affine):
    a, b, c, d, e, f = affine
    return [[a*x+b*y+c, d*x+e*y+f] for x, y in polygon]


def _recognize_page(image, page_number, metadata, engine, limits):
    import numpy as np
    width, height = image.size
    # RapidOCR ndarray input uses BGR; preview remains RGB.
    result = engine(np.asarray(image)[:, :, ::-1].copy())
    blocks = []
    if result.txts is not None:
        if result.boxes is None or result.scores is None or not len(result.txts) == len(result.boxes) == len(result.scores):
            fail('parse_process_failed')
        if len(result.txts) > limits.max_text_blocks:
            fail('document_too_large')
        for index, (text, score, box) in enumerate(zip(result.txts, result.scores, result.boxes), 1):
            if not isinstance(text, str) or not math.isfinite(float(score)) or not 0 <= float(score) <= 1:
                fail('parse_process_failed')
            if not text.strip():
                continue
            if len(box) != 4 or any(len(point) != 2 or not all(math.isfinite(float(v)) for v in point) for point in box):
                fail('parse_process_failed')
            polygon = [[float(max(0., min(width, x))), float(max(0., min(height, y)))] for x, y in box]
            blocks.append(OcrText(id=f'p{page_number}-t{index}', text=text, score=float(score), polygon=polygon,
                                  source=OcrSource(page_number=page_number, polygon=_map(polygon, metadata['pixel_to_source']),
                                                   coordinate_system=metadata['source_coordinate_system'], label=f'第{page_number}页')))
    elif result.boxes is not None:
        # Detection succeeded but recognition did not: not an empty document.
        fail('parse_process_failed')
    low = sum(block.score < limits.low_score_threshold for block in blocks)
    warnings = [Warning(code='low_confidence', message='部分文字置信度较低，请对照原图核对。', count=low)] if low else []
    preview = image.copy()
    preview.thumbnail((limits.preview_max_side, limits.preview_max_side))
    buffer = BytesIO()
    preview.save(buffer, format='JPEG', quality=85)
    payload = buffer.getvalue()
    preview.close()
    image_id = f'p{page_number}-preview'
    info = Image(id=image_id, part=f'ocr/page-{page_number}.jpg', mime='image/jpeg', size_bytes=len(payload),
                 sha256=hashlib.sha256(payload).hexdigest(), inline_preview=True)
    page = OcrPage(page_number=page_number, width=width, height=height, preview_image_id=image_id,
                   text_status='text' if blocks else 'no_text', text_blocks=blocks, warnings=warnings, **metadata)
    return page, info, payload


def parse_ocr(content: bytes, filename: str, file_type: str, page_numbers: list[int], settings: dict) -> OcrParseResult:
    limits = validate_inputs(content, filename, file_type, page_numbers, settings)
    from app.adapters.ocr_runtime import get_runtime
    pages, images, payloads = [], [], {}
    total_image_bytes = 0
    selected = sorted(page_numbers)

    def append(image, number, metadata):
        nonlocal total_image_bytes
        try:
            page, info, binary = _recognize_page(image, number, metadata, get_runtime(), limits)
        finally:
            image.close()
        total_image_bytes += len(binary)
        if total_image_bytes > limits.max_image_bytes or sum(len(p.text_blocks) for p in pages) + len(page.text_blocks) > limits.max_text_blocks:
            fail('document_too_large')
        pages.append(page); images.append(info)
        payloads[info.id] = base64.b64encode(binary).decode('ascii')

    if file_type != 'pdf':
        source_pages = 1
        image, metadata = _image(content, file_type, limits)
        append(image, 1, metadata)
    else:
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
        try:
            pdf = pdfium.PdfDocument(content)
        except pdfium.PdfiumError as exc:
            fail('encrypted_document' if exc.err_code == 4 else 'invalid_document')
        try:
            if raw.FPDF_GetSecurityHandlerRevision(pdf) >= 0:
                fail('encrypted_document')
            source_pages = len(pdf)
            if source_pages > limits.max_pages:
                fail('document_too_large')
            if max(selected) > source_pages:
                fail('invalid_document', '所选物理页不存在。')
            for number in selected:
                page = pdf[number - 1]
                bitmap = None
                try:
                    scale = limits.render_dpi / 72
                    if math.ceil(page.get_width()*scale) * math.ceil(page.get_height()*scale) > limits.max_render_pixels:
                        fail('document_too_large', '所选页渲染像素超过限制。')
                    bitmap = page.render(scale=scale)
                    conversion = bitmap.get_posconv(page)
                    x0, y0 = conversion.to_page(0, 0)
                    x1, y1 = conversion.to_page(1, 0)
                    x2, y2 = conversion.to_page(0, 1)
                    affine = [x1-x0, x2-x0, x0, y1-y0, y2-y0, y0]
                    metadata = dict(rotation=page.get_rotation(), source_width=float(page.get_width()),
                                    source_height=float(page.get_height()), source_coordinate_system='pdf_points_bottom_left',
                                    pixel_to_source=affine, transforms=[f'pdfium_render_dpi:{limits.render_dpi}', 'rgb_white_background'])
                    append(bitmap.to_pil().convert('RGB'), number, metadata)
                finally:
                    if bitmap is not None:
                        bitmap.close()
                    page.close()
        except pdfium.PdfiumError:
            fail('invalid_document')
        finally:
            pdf.close()
    document = OcrDocument(filename=filename, parser_version=PARSER_VERSION, source_type=file_type,
                           source_pages=source_pages, selected_pages=selected, pages=pages, images=images,
                           warnings=[Warning(code='unreviewed', message='所有识别文字均待人工核对。', count=sum(len(p.text_blocks) for p in pages))],
                           counts=OcrCounts(pages=len(pages), text_blocks=sum(len(p.text_blocks) for p in pages),
                                            images=len(images), pages_without_text=sum(p.text_status == 'no_text' for p in pages)))
    if len(document.model_dump_json().encode('utf-8')) > limits.max_json_bytes:
        fail('document_too_large')
    return OcrParseResult(document=document, image_payloads=payloads)
