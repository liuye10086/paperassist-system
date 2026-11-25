import base64
from io import BytesIO
from random import Random

from PIL import Image, PngImagePlugin
import pytest

from app.core.exceptions import StorageError


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


def image_bytes(image, format='PNG', **options):
    result = BytesIO()
    image.save(result, format, **options)
    return result.getvalue()


def figure(number, **fields):
    return dict(id=f'f{number}', number=number, title=f'Figure {number}', caption=f'Caption {number}', **fields)


def section(identity, *, inline=(), tail=()):
    return dict(id=identity, paragraphs=[{'figures': list(inline)}], groups=[{'figures': list(tail)}])


def image_url(raw, media='image/png'):
    return f'data:{media};base64,' + base64.b64encode(raw).decode('ascii')


def packed_bytes(value):
    return base64.b64decode(value['image_url'].split(',', 1)[1], validate=True)


def freeze(monkeypatch, sections, raw, targets=('introduction',)):
    from app.domain.manuscript_writing import revision_figures

    candidate = {'results_groups': [{'figures': [figure(100)]}], 'sources': []}
    calls = []

    def read(_manuscripts, project, subset):
        assert project == 'project'
        assert subset['sources'] is candidate['sources']
        calls.append([f['id'] for group in subset['results_groups'] for f in group['figures']])
        return raw

    monkeypatch.setattr(revision_figures, 'images_for', read)
    return revision_figures.freeze_revision_figures(None, 'project', candidate, sections, targets), calls


def test_loads_selected_figures_once_in_reading_order(monkeypatch):
    inline, tail, shared, excluded, discussion = map(figure, (3, 1, 4, 2, 5))
    sections = [
        section('introduction', inline=[inline, shared], tail=[tail, shared]),
        section('theme', inline=[excluded]),
        section('discussion', inline=[shared], tail=[discussion]),
    ]
    image = Image.new('RGB', (24, 16), '#1e70a0')
    png = image_bytes(image)
    jpeg = image_bytes(image, 'JPEG')
    result, calls = freeze(monkeypatch, sections, {'f3': png, 'f4': png, 'f1': jpeg, 'f5': png},
                           targets=('discussion', 'introduction'))
    assert calls == [['f3', 'f4', 'f1', 'f5']]
    assert [{key: value for key, value in item.items() if key != 'image_url'} for item in result] == [
        dict(number=3, section_ids=['introduction'], title='Figure 3', caption='Caption 3'),
        dict(number=4, section_ids=['introduction', 'discussion'], title='Figure 4', caption='Caption 4'),
        dict(number=1, section_ids=['introduction'], title='Figure 1', caption='Caption 1'),
        dict(number=5, section_ids=['discussion'], title='Figure 5', caption='Caption 5'),
    ]
    for item, source in zip(result, (png, png, jpeg, png), strict=True):
        with Image.open(BytesIO(packed_bytes(item))) as output, Image.open(BytesIO(source)) as preview:
            assert output.format == preview.format and output.size == preview.size
            assert output.getpixel((0, 0)) == preview.getpixel((0, 0))


def test_empty_selected_chapter_needs_no_image_read(monkeypatch):
    assert freeze(monkeypatch, [section('introduction'), section('theme', tail=[figure(1)])], {}) == ([], [])


@pytest.mark.parametrize('kind', ['tiff', 'svg'])
def test_uses_the_existing_rendered_bitmap_for_supported_source_formats(monkeypatch, kind):
    first = Image.new('RGB', (24, 16), '#1e70a0')
    if kind == 'tiff':
        raw = image_bytes(first, 'TIFF', save_all=True, append_images=[Image.new('RGB', first.size, 'red')])
        item = figure(1, original_image_format='tiff')
    else:
        data_url = image_url(image_bytes(first))
        raw = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
               f'<image xlink:href="{data_url}"/></svg>').encode()
        item = figure(1, research_member_format='svg')
    result, _ = freeze(monkeypatch, [section('introduction', tail=[item])], {'f1': raw})
    expected_prefix, encoded = result[0]['image_url'].split(',', 1)
    assert expected_prefix == 'data:image/png;base64'
    with Image.open(BytesIO(base64.b64decode(encoded, validate=True))) as output:
        assert output.size == first.size
        assert output.getpixel((0, 0)) == first.getpixel((0, 0))


def test_bounds_dimensions_without_cropping_or_replacing_the_source(monkeypatch):
    from app.domain.manuscript_writing import revision_figures

    monkeypatch.setattr(revision_figures, 'MAX_REVISION_FIGURE_SIDE', 160)
    raw = image_bytes(Image.new('RGB', (320, 128), '#1e70a0'))
    result, _ = freeze(monkeypatch, [section('introduction', inline=[figure(1)])], {'f1': raw})
    assert result[0]['image_url'].startswith('data:image/png;base64,')
    with Image.open(BytesIO(packed_bytes(result[0]))) as output:
        assert output.size == (160, 64)
    with Image.open(BytesIO(raw)) as original:
        assert original.size == (320, 128)


def test_oversized_rgb_png_uses_a_bounded_jpeg_at_the_same_dimensions(monkeypatch):
    from app.domain.manuscript_writing import revision_figures

    image = Image.frombytes('L', (512, 320), Random(37).randbytes(512 * 320)).convert('RGB')
    raw = image_bytes(image)
    monkeypatch.setattr(revision_figures, 'MAX_REVISION_FIGURE_BYTES', 200_000)
    assert len(raw) > revision_figures.MAX_REVISION_FIGURE_BYTES
    result, _ = freeze(monkeypatch, [section('introduction', inline=[figure(1)])], {'f1': raw})
    prefix, encoded = result[0]['image_url'].split(',', 1)
    assert prefix == 'data:image/jpeg;base64'
    packed = base64.b64decode(encoded, validate=True)
    assert len(packed) <= revision_figures.MAX_REVISION_FIGURE_BYTES
    with Image.open(BytesIO(packed)) as output:
        assert output.size == image.size


@pytest.mark.parametrize('format', ['PNG', 'JPEG'])
def test_outbound_copy_drops_source_metadata_and_trailing_content(monkeypatch, format):
    private = 'private source metadata'
    if format == 'PNG':
        info = PngImagePlugin.PngInfo()
        info.add_text('Comment', private)
        options = {'pnginfo': info}
    else:
        exif = Image.Exif()
        exif[270] = private
        options = {'exif': exif}
    image = Image.new('RGB', (24, 16), '#1e70a0')
    tail = b'trailing private content'
    raw = image_bytes(image, format, **options) + tail
    result, _ = freeze(monkeypatch, [section('introduction', inline=[figure(1)])], {'f1': raw})
    packed = packed_bytes(result[0])
    assert private.encode() in raw and private.encode() not in packed
    assert tail not in packed
    with Image.open(BytesIO(packed)) as output:
        assert not output.getexif() and 'Comment' not in output.info


def test_jpeg_orientation_is_applied_to_the_clean_raster_copy(monkeypatch):
    exif = Image.Exif()
    exif[274] = 6
    raw = image_bytes(Image.new('RGB', (24, 16), '#1e70a0'), 'JPEG', exif=exif)
    result, _ = freeze(monkeypatch, [section('introduction', inline=[figure(1)])], {'f1': raw})
    with Image.open(BytesIO(packed_bytes(result[0]))) as output:
        assert output.format == 'JPEG' and output.size == (16, 24)
        assert not output.getexif()


@pytest.mark.parametrize('raw', [{}, {'f1': b'not an image'}])
def test_unavailable_figure_blocks_the_whole_request(monkeypatch, raw):
    with pytest.raises(StorageError) as error:
        freeze(monkeypatch, [section('introduction', inline=[figure(1)])], raw)
    assert error.value.code == 'task_source_conflict'


@pytest.mark.parametrize('bound', ['count', 'total', 'individual'])
def test_figure_budget_blocks_the_whole_request(monkeypatch, bound):
    from app.domain.manuscript_writing import revision_figures

    raw = image_bytes(Image.new('RGBA', (24, 16), (123, 43, 61, 10)))
    name, limit = {
        'count': ('MAX_REVISION_FIGURES', 1),
        'total': ('MAX_REVISION_FIGURE_TOTAL_BYTES', 2 * len(raw) - 1),
        'individual': ('MAX_REVISION_FIGURE_BYTES', 10),
    }[bound]
    monkeypatch.setattr(revision_figures, name, limit)
    with pytest.raises(StorageError) as error:
        freeze(monkeypatch, [section('introduction', inline=[figure(1), figure(2)])], {'f1': raw, 'f2': raw})
    assert error.value.code == 'manuscript_writing_input_limit'
