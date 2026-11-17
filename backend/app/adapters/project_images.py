"""Bounded decoding of uploaded project images; original bytes remain unchanged."""
from contextlib import contextmanager
from io import BytesIO

from PIL import Image

from app.core.exceptions import StorageError


IMAGE_MEDIA_TYPES = {'png': 'image/png', 'jpeg': 'image/jpeg', 'tiff': 'image/tiff'}
IMAGE_FORMATS = {'png': 'PNG', 'jpeg': 'JPEG', 'tiff': 'TIFF'}
INVALID_PROJECT_IMAGE = 'project_image_invalid'
MAX_IMAGE_SIDE = 8000
MAX_IMAGE_PIXELS = 40_000_000
PREVIEW_MAX_SIDE = 1600
WORD_MAX_SIDE = 2400
TIFF_WORD_RENDERER_VERSION = 'tiff-first-page-png-v1'


@contextmanager
def _decoded_image(content: bytes, file_type: str):
    expected = IMAGE_FORMATS[file_type]
    try:
        with Image.open(BytesIO(content), formats=[expected]) as image:
            if (image.format != expected or min(image.size) < 1 or max(image.size) > MAX_IMAGE_SIDE
                    or image.width * image.height > MAX_IMAGE_PIXELS):
                raise ValueError('Image format or dimensions')
            # Pillow opens frame zero. Deliberately avoid scanning the later TIFF
            # pages: they are retained in the original and are not used here.
            if file_type != 'tiff' and getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Expected a static image')
            image.load()
            yield image
    except (OSError, ValueError, TypeError, SyntaxError, EOFError, OverflowError, IndexError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise StorageError(INVALID_PROJECT_IMAGE, '图片格式不符、文件损坏或像素尺寸超过支持范围。', 422) from exc


def validate_project_image(content: bytes, file_type: str):
    with _decoded_image(content, file_type):
        pass


def tiff_as_png(content: bytes, *, max_side: int) -> bytes:
    """Project the first TIFF page to a browser and Word compatible PNG."""
    with _decoded_image(content, 'tiff') as image:
        high_depth = image.mode.startswith('I;16')
        mode = 'I' if high_depth else 'RGBA' if image.has_transparency_data else 'L' if image.mode in ('1', 'L') else 'RGB'
        with image.convert(mode) as display:
            display.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            display.info.clear()
            output = BytesIO()
            if high_depth:
                with display.convert('I;16') as grayscale:
                    grayscale.save(output, 'PNG')
            else:
                display.save(output, 'PNG')
            return output.getvalue()
