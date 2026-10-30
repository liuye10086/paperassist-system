"""Image format and scaled-coordinate checks; no OCR or interpretation."""
import io
import warnings

from PIL import Image

from app.domain.bioinformatics.parser_contracts import BioParseError


def inspect_image(content, limits, budget):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                width, height = image.size
                if width * height > limits.max_image_pixels:
                    raise BioParseError("bio_input_limit", "image_pixels")
                if image.format not in {"PNG", "JPEG"}:
                    raise BioParseError("bio_components_mismatch", "image_format")
                decoded_bytes = width * height * max(len(image.getbands()), 4)
                budget.expanded += decoded_bytes
                if budget.expanded > limits.max_expanded_bytes:
                    raise BioParseError("bio_input_limit", "image_expanded_bytes")
                image.verify()
            with Image.open(io.BytesIO(content)) as image:
                image.load()
                return {"width": width, "height": height, "format": image.format.lower()}
    except BioParseError:
        raise
    except Exception:
        raise BioParseError("bio_components_mismatch", "image_integrity") from None


def check_image_bounds(positions, scale, dimensions):
    for position in positions:
        x, y = position["pxl_col_in_fullres"] * scale, position["pxl_row_in_fullres"] * scale
        if x < -1 or y < -1 or x > dimensions["width"] or y > dimensions["height"]:
            raise BioParseError("bio_components_mismatch", "scaled_coordinates_outside_image")
