"""Freeze selected manuscript figures as model image inputs."""

import base64
from io import BytesIO
from itertools import chain

from PIL import Image, ImageOps

from app.adapters.project_images import MAX_IMAGE_PIXELS, MAX_IMAGE_SIDE, tiff_as_png
from app.adapters.research_report_images import as_png
from app.adapters.task_store import source_conflict
from app.core.exceptions import StorageError
from app.domain.manuscripts.execution import images_for


MAX_REVISION_FIGURES = 8
MAX_REVISION_FIGURE_BYTES = 4 * 1024**2
MAX_REVISION_FIGURE_TOTAL_BYTES = 8 * 1024**2
MAX_REVISION_FIGURE_SIDE = 2560
MAX_SCI_INITIAL_FIGURES = 20
MAX_SCI_INITIAL_FIGURE_SIDE = 1600
REVISION_FIGURE_FORMATS = {'image/png': 'PNG', 'image/jpeg': 'JPEG'}


def figure_limits(sci_initial):
    if sci_initial:
        return MAX_SCI_INITIAL_FIGURES, MAX_SCI_INITIAL_FIGURES * MAX_REVISION_FIGURE_BYTES
    return MAX_REVISION_FIGURES, MAX_REVISION_FIGURE_TOTAL_BYTES


def _input_limit():
    return StorageError('manuscript_writing_input_limit', '本次写作的图片超过输入上限，请减少所选图件。', 422)


def _revision_image(figure, raw, max_side):
    if not figure.get('language_version_id'):
        if figure.get('original_image_format') == 'tiff':
            raw = tiff_as_png(raw, max_side=max_side)
        elif figure.get('research_member_format'):
            raw = as_png(raw, figure['research_member_format'])

    with Image.open(BytesIO(raw), formats=tuple(REVISION_FIGURE_FORMATS.values())) as image:
        if (max(image.size) > MAX_IMAGE_SIDE or image.width * image.height > MAX_IMAGE_PIXELS
                or getattr(image, 'n_frames', 1) != 1):
            raise source_conflict()
        ImageOps.exif_transpose(image, in_place=True)
        mode = 'RGBA' if image.has_transparency_data else image.mode
        if mode not in ('L', 'I;16', 'RGB', 'RGBA'):
            mode = 'RGB'
        formats = ['PNG']
        if image.format == 'JPEG':
            formats.insert(0, 'JPEG')
        elif mode == 'RGB':
            formats.append('JPEG')
        with image.convert(mode) as display:
            display.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            # Encode only the rendered pixels. Source EXIF, comments and trailing data stay local.
            display.info.clear()
            for format in formats:
                options = dict(quality=95, subsampling=0, optimize=True) if format == 'JPEG' else {}
                with BytesIO() as output:
                    display.save(output, format, **options)
                    if output.tell() <= MAX_REVISION_FIGURE_BYTES:
                        return f'image/{format.lower()}', output.getvalue()
    raise _input_limit()


def figure_context(figure, section_ids):
    return dict(number=figure['number'], section_ids=section_ids, title=figure['title'], caption=figure['caption'])


def _pack_figures(manuscripts, project, snapshot, matches, *, sci_initial=False):
    if not matches:
        return []
    max_figures, max_total_bytes = figure_limits(sci_initial)
    if len(matches) > max_figures:
        raise _input_limit()

    max_side = MAX_SCI_INITIAL_FIGURE_SIDE if sci_initial else MAX_REVISION_FIGURE_SIDE
    selected = {**snapshot, 'results_groups': [{'figures': [item for item, _ in matches.values()]}]}
    packed = []
    total_bytes = 0
    try:
        images = images_for(manuscripts, project, selected)
        for figure_id, (figure, section_ids) in matches.items():
            media, raw = _revision_image(figure, images[figure_id], max_side)
            total_bytes += len(raw)
            if total_bytes > max_total_bytes:
                raise _input_limit()
            data = base64.b64encode(raw).decode('ascii')
            packed.append(dict(figure_context(figure, section_ids), image_url=f'data:{media};base64,{data}'))
    except (KeyError, StopIteration, OSError, SyntaxError, TypeError, ValueError, Image.DecompressionBombError) as exc:
        raise source_conflict() from exc
    return packed


def initial_figure_matches(snapshot, selected_source_ids):
    """Use the saved SCI resource assignments in the frozen manuscript, within the selected source scope."""
    selected = set(selected_source_ids)
    plan = snapshot.get('paper_plan') or {}
    placements = {row['figure_id']: row['chapter_id'] for row in plan.get('sci_figures', ())
                  if row['figure_id'] in selected}
    matches = {}
    if placements:
        for group in snapshot['results_groups']:
            chapter = group.get('illustration_chapter_id')
            if chapter is None:
                continue
            for figure in group['figures']:
                sources = figure['source_ids']
                if sources and placements.get(sources[0]) == chapter and set(sources) <= selected:
                    matches[figure['id']] = (figure, [chapter])
    return matches


def freeze_initial_figures(manuscripts, project, snapshot, selected_source_ids):
    return _pack_figures(manuscripts, project, snapshot, initial_figure_matches(snapshot, selected_source_ids),
                         sci_initial=True)


def freeze_revision_figures(manuscripts, project, candidate, rendered_sections, target_sections):
    """Read each selected figure once, using the reader's order and original figure numbers."""
    targets = set(target_sections)
    matches = {}
    for section in rendered_sections:
        sid = section['id']
        if sid not in targets:
            continue
        for container in chain(section['paragraphs'], section['groups']):
            for figure in container.get('figures', ()):
                original, section_ids = matches.setdefault(figure['id'], (figure, []))
                if original != figure:
                    raise source_conflict()
                if sid not in section_ids:
                    section_ids.append(sid)
    return _pack_figures(manuscripts, project, candidate, matches)
