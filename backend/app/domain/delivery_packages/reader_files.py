"""Project frozen artifacts to human filenames without changing their identity."""
from datetime import datetime
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
import re
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from app.adapters.research_results_store import invalid
from app.domain.bioinformatics.artifact_names import analysis_figure_name, single_cell_report_name


def native_filename(proof):
    if proof['kind'] == 'single_cell_word':
        return single_cell_report_name(bool(proof.get('annotation')))
    if proof['kind'] == 'bulk_word':
        return '转录组学分析报告.docx'
    return analysis_figure_name(proof.get('member_key', ''), proof.get('figure_kind')) + '.png'


def analyst_file_names(db, store, project, file_ids):
    if store.assignment is None or not file_ids:
        return {}
    return {row['file_id']: native_filename(row['provenance_json']) for row in db.execute(
        'SELECT file_id,provenance_json FROM delivery_artifact_sources WHERE project_id=%s AND file_id=ANY(%s)',
        (project, file_ids),
    )}


def safe_filename(name, fallback):
    basename = re.split(r'[/\\]', name)[-1]
    basename = re.sub(r'[<>:"|?*\x00-\x1f\x7f\u202a-\u202e\u2066-\u2069]', '', basename).strip(' .')
    path = PurePosixPath(basename or fallback)
    stem = path.stem
    if re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])', stem.split('.')[0]):
        stem = '_' + stem
    return stem.encode()[:200].decode(errors='ignore').rstrip(' .') + path.suffix[:20]


def research_member_filename(kind, fmt, title=None):
    label = '分析图件' if kind == 'research_figure_member' else '分析结果表' if fmt == 'xlsx' else '分析报告'
    return safe_filename(f'{title or label}.{fmt}', f'{label}.{fmt}')


def analysis_member_filenames(db, project, members):
    files = [m['selection']['file_id'] for m in members if m['selection']['kind'] == 'file'
             and not m['source_metadata'].get('analysis_artifact')]
    filenames = {row['id']: row['filename'] for row in db.execute(
        'SELECT id,filename FROM files WHERE project_id=%s AND id=ANY(%s)', (project, files)
    )} if files else {}
    titles = {}
    for family, column in (('figure', 'config_json'), ('report', 'content_json')):
        ids = [m['selection']['version_id'] for m in members if m['selection']['kind'] == f'research_{family}_member']
        if ids:
            titles.update({row['id']: row['title'] for row in db.execute(
                f"SELECT id,{column}->>'title' AS title FROM research_{family}_versions WHERE project_id=%s AND id=ANY(%s)",
                (project, ids),
            )})
    names = {}
    used = set()
    for member in members:
        kind = member['selection']['kind']
        fmt = member['format']
        proof = member['source_metadata'].get('analysis_artifact')
        if proof:
            name = native_filename(proof)
        elif kind == 'file':
            name = filenames.get(member['selection']['file_id'], '交付附件.' + fmt)
        else:
            name = research_member_filename(kind, fmt, titles.get(member['selection'].get('version_id')))
        path = PurePosixPath(safe_filename(name, '分析成果.' + fmt))
        name = path.name
        number = 2
        while name.casefold() in used:
            name = f'{path.stem}（{number}）{path.suffix}'
            number += 1
        used.add(name.casefold())
        names[member['id']] = name
    return names


def analysis_package_filename(snapshot):
    stage = {'first': '首次交付', 'revision': '修订交付', 'final': '最终交付'}[snapshot['stage']]
    moment = datetime.fromisoformat(snapshot['created_at']).astimezone()
    return f'分析交付 - {stage} - {moment:%Y-%m-%d %H-%M-%S}.zip'


def reader_zip(stored, members, names):
    """Copy selected bytes from the already verified archive, without its audit files."""
    buffer = BytesIO()
    try:
        with ZipFile(BytesIO(stored)) as source, ZipFile(buffer, 'w') as output:
            for member in members:
                raw = source.read(member['name'])
                if len(raw) != member['size_bytes'] or sha256(raw).hexdigest() != member['sha256']:
                    raise invalid()
                info = ZipInfo(names[member['id']])
                info.compress_type = ZIP_DEFLATED
                output.writestr(info, raw)
    except (BadZipFile, KeyError) as exc:
        raise invalid('research_output_invalid') from exc
    return buffer.getvalue()
