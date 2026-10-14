"""Frozen OCR contract; safe to import without native OCR dependencies."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.domain.documents.contracts import Image, Warning

PARSER_VERSION = 'rapidocr-3.10.0-ppocrv6-small-v1'
PROCESS_SETTINGS = dict(timeout_seconds=180, cpu_seconds=120, memory_bytes=2147483648,
                        max_output_bytes=33554432)


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class OcrSettings(Model):
    max_upload_bytes: int = Field(default=10485760, gt=0, le=10485760)
    max_pages: int = Field(default=100, gt=0, le=100)
    max_selected_pages: int = Field(default=10, gt=0, le=10)
    max_image_pixels: int = Field(default=20000000, gt=0, le=20000000)
    max_render_pixels: int = Field(default=12000000, gt=0, le=12000000)
    max_json_bytes: int = Field(default=4194304, gt=0, le=4194304)
    max_image_bytes: int = Field(default=16777216, gt=0, le=16777216)
    max_text_blocks: int = Field(default=20000, gt=0, le=20000)
    render_dpi: Literal[200] = 200
    preview_max_side: Literal[1600] = 1600
    low_score_threshold: Literal[0.8] = 0.8


MODEL_SETTINGS = dict(engine='rapidocr==3.10.0', runtime='onnxruntime==1.24.4',
                      detector='PP-OCRv6_det_small', recognizer='PP-OCRv6_rec_small',
                      classifier='ch_ppocr_mobile_v2.0_cls_mobile', device='cpu', threads=1)
MODEL_HASHES = {
    'PP-OCRv6_det_small.onnx': '090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f',
    'PP-OCRv6_rec_small.onnx': '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884',
    'ch_ppocr_mobile_v2.0_cls_mobile.onnx': 'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c',
}
MODEL_SETTINGS['sha256'] = MODEL_HASHES.copy()
MODEL_SETTINGS['dictionary_sha256'] = 'f7aa897ca828a4c7c9e2739c30f9161a33306d532f020bcdb91dcfb664a5507e'
OCR_SETTINGS = dict(ocr=OcrSettings().model_dump(), process=PROCESS_SETTINGS.copy(),
                    models=MODEL_SETTINGS.copy())
Point = Annotated[list[float], Field(min_length=2, max_length=2)]
Polygon = Annotated[list[Point], Field(min_length=4, max_length=4)]


class OcrSource(Model):
    page_number: int = Field(gt=0, le=100)
    polygon: Polygon
    coordinate_system: Literal['pdf_points_bottom_left', 'image_pixels_top_left']
    label: str


class OcrText(Model):
    kind: Literal['ocr_text'] = 'ocr_text'
    id: str
    text: str
    score: float = Field(ge=0, le=1)
    review_status: Literal['unreviewed'] = 'unreviewed'
    polygon: Polygon
    source: OcrSource


class OcrPage(Model):
    page_number: int = Field(gt=0, le=100)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    preview_image_id: str
    rotation: Literal[0, 90, 180, 270]
    source_width: float = Field(gt=0)
    source_height: float = Field(gt=0)
    source_coordinate_system: Literal['pdf_points_bottom_left', 'image_pixels_top_left']
    # Affine [a,b,c,d,e,f]: source x=a*x+b*y+c; source y=d*x+e*y+f.
    pixel_to_source: list[float] = Field(min_length=6, max_length=6)
    transforms: list[str]
    text_status: Literal['text', 'no_text']
    text_blocks: list[OcrText]
    warnings: list[Warning]

    @field_validator('rotation', mode='before')
    @classmethod
    def strict_rotation(cls, value):
        if type(value) is not int:
            raise ValueError('rotation must be an integer')
        return value


class OcrCounts(Model):
    pages: int = Field(ge=0, le=10)
    text_blocks: int = Field(ge=0, le=20000)
    images: int = Field(ge=0, le=10)
    pages_without_text: int = Field(ge=0, le=10)


class OcrDocument(Model):
    schema_version: Literal[1] = 1
    kind: Literal['ocr_document'] = 'ocr_document'
    filename: str
    parser_version: str
    source_type: Literal['pdf', 'png', 'jpeg']
    source_pages: int = Field(gt=0, le=100)
    selected_pages: list[int] = Field(min_length=1, max_length=10)
    pages: list[OcrPage] = Field(min_length=1, max_length=10)
    images: list[Image]
    warnings: list[Warning]
    counts: OcrCounts

    @field_validator('schema_version', mode='before')
    @classmethod
    def strict_schema_version(cls, value):
        if type(value) is not int:
            raise ValueError('schema_version must be an integer')
        return value


class OcrParseResult(Model):
    document: OcrDocument
    image_payloads: dict[str, str]
