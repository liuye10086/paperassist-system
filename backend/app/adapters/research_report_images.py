"""Read the single scientific bitmap of a verified research figure member."""
import base64
import io
import xml.etree.ElementTree as ET
from PIL import Image


def as_png(raw,format):
    if format=='svg':
        if b'<!' in raw:raise ValueError('Unexpected SVG declaration')
        root=ET.fromstring(raw);images=root.findall('{http://www.w3.org/2000/svg}image')
        if root.tag!='{http://www.w3.org/2000/svg}svg' or len(images)!=1:raise ValueError('Expected a single fixed bitmap')
        uri=images[0].attrib.get('{http://www.w3.org/1999/xlink}href','')
        if not uri.startswith('data:image/png;base64,'):raise ValueError('No fixed bitmap in SVG')
        raw=base64.b64decode(uri.split(',',1)[1],validate=True)
    elif format=='pdf':
        import pdfplumber
        with pdfplumber.open(io.BytesIO(raw)) as document:
            if len(document.pages)!=1 or len(document.pages[0].images)!=1:raise ValueError('Expected a single fixed bitmap page')
            image=document.pages[0].images[0]
            if image['bits']!=8:raise ValueError('Unsupported fixed bitmap depth')
            raw=image['stream'].get_data()
    elif format not in ('png','tiff','jpeg'):raise ValueError('Unsupported figure member')
    with Image.open(io.BytesIO(raw)) as image:
        if max(image.size)>8000 or image.width*image.height>40_000_000 or getattr(image,'n_frames',1)!=1:raise ValueError('Figure pixel limit')
        image.load();output=io.BytesIO();image.convert('RGB').save(output,'PNG')
        return output.getvalue()
