"""Prepare/run the B04 -> B03 downstream engineering acceptance through local APIs.

No service lifecycle, science computation, paid model or external network calls.
Default mode is offline preparation. --execute writes only in the verified B04
copy; --publish is a separate explicit gate for new manuscript roots.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import time
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'script/dev'), str(ROOT / 'backend')]
REPORT_ZIP_MAX_MEMBERS = 256
REPORT_ZIP_MAX_BYTES = 256 * 1024 * 1024
REPORT_FILES = {'docx': ('analysis', 'docx'), 'xlsx': ('results', 'xlsx'),
                'methods': ('methods', 'txt'), 'manifest': ('manifest', 'json'), 'zip': ('analysis_package', 'zip')}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _exact_bytes(raw, member):
    if (type(member.get('size_bytes')) is not int or not 0 <= member['size_bytes'] <= REPORT_ZIP_MAX_BYTES
            or not isinstance(member.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', member['sha256'])
            or len(raw) != member['size_bytes'] or sha(raw) != member['sha256']):
        raise ValueError('Bytes differ from exact member SHA/size')


def _unique_json(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate package JSON key')
        value[key] = item
    return value


def _safe_package_name(name):
    return (isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', name)
            and all(part not in ('.', '..') for part in name.split('/')))


def _redirected_path(path):
    # lstat also detects Windows junctions on Python versions without is_junction.
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


def verified_report_zip(raw, formal):
    """Read bounded bytes in memory; never extract archive-selected paths."""
    _exact_bytes(raw, formal['zip'])
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if (len(infos) > REPORT_ZIP_MAX_MEMBERS or len(set(names)) != len(names)
                or sum(info.file_size for info in infos) > REPORT_ZIP_MAX_BYTES
                or any(not _safe_package_name(info.filename) or info.is_dir() or info.external_attr & 0x10 or info.flag_bits & 1
                       or ((info.external_attr >> 16) & 0o170000) not in (0, 0o100000) for info in infos)):
            raise ValueError('Unsafe or oversized report ZIP')
        if not {'manifest.json', 'SHA256SUMS.txt'} <= set(names):
            raise ValueError('Report ZIP manifest/checksums missing')
        manifest_raw = archive.read('manifest.json')
        manifest = json.loads(manifest_raw, object_pairs_hook=_unique_json)
        if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int
                or manifest['schema_version'] != 1 or not isinstance(manifest.get('members'), list)):
            raise ValueError('Invalid report ZIP manifest')
        entries = manifest['members']
        declared = []
        for member in entries:
            if (not isinstance(member, dict) or set(member) != {'name', 'size_bytes', 'sha256'}
                    or not _safe_package_name(member['name']) or member['name'] in ('manifest.json', 'SHA256SUMS.txt')):
                raise ValueError('Invalid report ZIP member declaration')
            declared.append(member['name'])
        if len(set(declared)) != len(declared) or set(names) != set(declared) | {'manifest.json', 'SHA256SUMS.txt'}:
            raise ValueError('Report ZIP member set differs')
        selected = {'manifest.json': manifest_raw}
        wanted = {key + '.' + fmt for role, (key, fmt) in REPORT_FILES.items() if role not in ('zip', 'manifest')}
        for member in entries:
            content = archive.read(member['name'])
            _exact_bytes(content, member)
            if member['name'] in wanted:
                selected[member['name']] = content
        sums = ''.join(m['sha256'] + '  ' + m['name'] + '\n' for m in entries)
        sums += sha(manifest_raw) + '  manifest.json\n'
        if archive.read('SHA256SUMS.txt') != sums.encode('utf-8'):
            raise ValueError('Report ZIP checksums differ')
        raws = {'zip': raw}
        for role, (key, fmt) in REPORT_FILES.items():
            if role == 'zip':
                continue
            name = key + '.' + fmt
            if name not in selected:
                raise ValueError('Formal report member missing from ZIP: ' + name)
            _exact_bytes(selected[name], formal[role])
            raws[role] = selected[name]
        return raws, len(entries)


def literal_rows(raw, fmt):
    rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig')), delimiter='\t' if fmt == 'tsv' else ',', strict=True))
    if not rows or not rows[0] or len(set(rows[0])) != len(rows[0]) or any(len(r) != len(rows[0]) for r in rows[1:]):
        raise ValueError('Invalid literal source table')
    return rows[0], rows[1:]


def literal_tag(value):
    if value == 'NA':
        return 'NA'
    try:
        number = Decimal(value)
        if number.is_finite() and number.is_zero():
            return 'zero'
    except InvalidOperation:
        pass
    return None


def verify_workbook(raw, counts, source_tables):
    """Compare every exported cell to its original text; blanks are OOXML empty cells."""
    from openpyxl import load_workbook
    book = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
    checked = []
    try:
        for entry in counts['tables']:
            identity = entry['source']['source_id']
            original = source_tables[identity]
            if entry['sha256'] != original['sha256'] or entry['rows'] != len(original['rows']):
                raise AssertionError('Export table identity/row count differs: ' + identity)
            actual = []
            for name in entry['sheets']:
                rows = book[name].iter_rows()
                if [c.value for c in next(rows)] != original['columns']:
                    raise AssertionError('Export header differs: ' + identity)
                for cells in rows:
                    # Source tables are literal text, including =..., 0 and NA.
                    if any(c.data_type == 'f' for c in cells):
                        raise AssertionError('Formula injected into a literal result table')
                    actual.append(['' if c.value is None else str(c.value) for c in cells])
            if actual != original['rows']:
                raise AssertionError('Complete workbook values differ: ' + identity)
            checked.append(dict(source_id=identity, rows=len(actual), source_sha256=entry['sha256'],
                raw_zero_cells=sum(literal_tag(v) == 'zero' for row in actual for v in row),
                raw_NA_cells=sum(v == 'NA' for row in actual for v in row)))
    finally:
        book.close()
    return checked


class Ledger:
    """Persist before POST; an unknown mutation must be read back before retry."""
    def __init__(self, path, identity, retries=()):
        self.path = Path(path)
        self.identity = identity
        self.retries = set(retries)
        self.record = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else dict(
            identity=identity, actions={}, status='prepared', real_model_calls=0,
            user_acceptance='pending', biological_validation='not_performed', word_visual_review='not_performed')
        if self.record['identity'] != identity:
            raise ValueError('Retained run identity differs; use a separate output directory')

    def save(self):
        import worker_stack
        self.path.parent.mkdir(parents=True, exist_ok=True)
        worker_stack.private_write(self.path, json.dumps(self.record, ensure_ascii=False, indent=2, default=str))

    def post(self, label, path, body, send, recover):
        entry = self.record['actions'].get(label)
        fresh = entry is None
        if fresh:
            entry = dict(key='b04-downstream-' + uuid4().hex, path=path, body=body, digest=digest(body), status='submitting')
            self.record['actions'][label] = entry
            self.save()
        elif entry['path'] != path or entry['digest'] != digest(body):
            raise ValueError('Frozen request changed: ' + label)
        if entry.get('response') is not None:
            return entry['response']
        if not fresh:
            value = recover(entry)
            if value is not None:
                entry.update(status='recovered', response=value)
                self.save()
                return value
            if label not in self.retries:
                entry['status'] = 'unknown_not_found'
                self.save()
                raise RuntimeError('Original request not yet found; no POST repeated. Explicit --retry-original ' + label + ' is required')
        try:
            value = send(entry)
        except Exception:
            entry['status'] = 'unknown'
            self.save()
            raise
        entry.update(status='returned', response=value)
        self.save()
        return value


class Acceptance:
    def __init__(self, args, state, output):
        import httpx
        self.args, self.state, self.output = args, state, output
        self.base = '/api/v1/projects/' + args.project_id
        identity = dict(schema=state['schema'], project_id=args.project_id, result_ids=args.result_id,
                        figure_result_ids=args.figure_result_id, manuscript_mode='new_roots_only')
        self.ledger = Ledger(output / 'receipt.json', identity, args.retry_original)
        self.record = self.ledger.record
        credentials = json.loads((Path(state['assets']).parent / 'credentials.json').read_text(encoding='utf-8-sig'))['review']
        self.owner = credentials['id']
        self.client = httpx.Client(base_url=state['url'], timeout=httpx.Timeout(7200, connect=30), trust_env=False,
            headers={'Origin': state['url'], 'X-PaperAssist-Client': 'web'})
        response = self.check(self.client.post('/api/v1/auth/login', json={k: credentials[k] for k in ('email', 'password')},
                                               timeout=httpx.Timeout(7200, connect=30)))
        self.client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        # Credentials, cookies and CSRF are never recorded or printed.
        self.source_tables = {}

    @staticmethod
    def check(response):
        if response.status_code not in (200, 201, 202):
            try:
                detail = response.json().get('detail', {})
                code = detail.get('code', 'invalid_request') if isinstance(detail, dict) else 'invalid_request'
            except ValueError:
                code = 'unexpected_response'
            raise RuntimeError(f'HTTP {response.status_code}: {code}')
        return response

    def get(self, path):
        return self.check(self.client.get(path)).json()

    def write_json(self, name, value):
        target = self.output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and json.loads(target.read_text(encoding='utf-8')) != json.loads(json.dumps(value, default=str)):
            raise ValueError('Existing evidence differs; not overwriting: ' + name)
        if not target.exists():
            target.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

    def bytes(self, member, folder):
        if not member['download_url'].startswith(self.base + '/'):
            raise ValueError('Foreign download URL')
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / (re.sub(r'[^A-Za-z0-9_.-]', '_', member.get('key', member.get('id', 'output'))) + '.' + member.get('format', 'bin'))
        if target.exists():
            raw = target.read_bytes()
            if sha(raw) != member['sha256']:
                raise ValueError('Existing evidence hash differs; not overwriting')
        else:
            raw = self.check(self.client.get(member['download_url'])).content
            if sha(raw) != member['sha256']:
                raise ValueError('Downloaded bytes differ from the exact member SHA')
            target.write_bytes(raw)
        return raw

    def report_members(self, value, folder):
        """Acquire formal siblings through one verified ZIP, retaining exact files."""
        if not isinstance(value.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value['id']):
            raise ValueError('Invalid formal report identity')
        formal = {}
        for member in value['members']:
            role = member.get('role')
            if role not in REPORT_FILES or role in formal:
                raise ValueError('Unknown or duplicate formal report role')
            if (member.get('key'), member.get('format')) != REPORT_FILES[role]:
                raise ValueError('Unexpected formal report filename')
            if (type(member.get('size_bytes')) is not int or not 0 < member['size_bytes'] <= REPORT_ZIP_MAX_BYTES
                    or not isinstance(member.get('sha256'), str) or not re.fullmatch(r'[a-f0-9]{64}', member['sha256'])):
                raise ValueError('Invalid formal report SHA/size')
            identifier = member.get('id')
            if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', identifier):
                raise ValueError('Invalid formal report member identity')
            expected = self.base + '/research-reports/' + value['id'] + '/members/' + identifier + '/download'
            if member.get('download_url') != expected:
                raise ValueError('Foreign report member download URL')
            formal[role] = member
        if set(formal) != set(REPORT_FILES) or len({m['id'] for m in formal.values()}) != len(formal):
            raise ValueError('Formal report members are incomplete or duplicated')
        if (_redirected_path(folder)
                or not folder.resolve().is_relative_to(self.output.resolve())):
            raise ValueError('Unsafe report evidence folder')
        targets = {role: folder / (key + '.' + fmt) for role, (key, fmt) in REPORT_FILES.items()}
        retained = {}
        for role, target in targets.items():
            if _redirected_path(target):
                raise ValueError('Unsafe retained report evidence')
            if target.exists():
                if not target.is_file():
                    raise ValueError('Existing report evidence is not a file')
                if target.stat().st_size != formal[role]['size_bytes']:
                    raise ValueError('Existing report evidence size differs; not overwriting')
                retained[role] = target.read_bytes()
                _exact_bytes(retained[role], formal[role])
        zipped = retained.get('zip')
        if zipped is None:
            zipped = self.check(self.client.get(formal['zip']['download_url'])).content
        raws, count = verified_report_zip(zipped, formal)
        folder.mkdir(parents=True, exist_ok=True)
        # Every record, complete package and existing target was checked before
        # creating any output. Exclusive creation cannot overwrite a race winner.
        for role, target in targets.items():
            if role in retained:
                continue
            try:
                with target.open('xb') as stream:
                    stream.write(raws[role])
            except FileExistsError:
                if _redirected_path(target):
                    raise ValueError('Unsafe concurrent report evidence')
                _exact_bytes(target.read_bytes(), formal[role])
        acquisition = dict(method='verified_formal_report_zip', report_version_id=value['id'],
            archive_member_id=formal['zip']['id'], archive_sha256=formal['zip']['sha256'],
            archive_size_bytes=formal['zip']['size_bytes'], archive_download_url=formal['zip']['download_url'],
            archive_reuse='same SHA and size retained ZIP is verified without another HTTP request',
            standalone_member_endpoints_exercised=False, verified_package_members=count,
            derived_members=[dict(role=role, member_id=formal[role]['id'], package_path=key + '.' + fmt,
                                 sha256=formal[role]['sha256'], size_bytes=formal[role]['size_bytes'])
                             for role, (key, fmt) in REPORT_FILES.items() if role != 'zip'])
        self.write_json(str(folder.relative_to(self.output) / 'acquisition.json'), acquisition)
        return raws

    def lookup_sql(self, table, column, key, *, version=None):
        # Only exact scoped read-only recovery for APIs without a public key query.
        allowed = {('pdf_exports', 'request_key'), ('manuscript_exports', 'idempotency_key'),
                   ('school_template_versions', 'idempotency_key'), ('school_template_confirmations', 'idempotency_key')}
        if (table, column) not in allowed:
            raise ValueError('Unapproved recovery query')
        from app.db.database import database_connection
        with database_connection() as db:
            if table == 'manuscript_exports':
                row = db.execute('SELECT e.id FROM manuscript_exports e JOIN manuscript_versions v ON v.id=e.version_id WHERE v.project_id=%s AND v.user_id=%s AND e.version_id=%s AND e.idempotency_key=%s',
                                 (self.args.project_id, self.owner, version, key)).fetchone()
            else:
                row = db.execute('SELECT id FROM ' + table + ' WHERE project_id=%s AND user_id=%s AND ' + column + '=%s',
                                 (self.args.project_id, self.owner, key)).fetchone()
        return row['id'] if row else None

    def post(self, label, path, body, *, kind=None, recovery=None, send=None):
        def recover(entry):
            if recovery:
                return recovery(entry)
            response = self.client.get(self.base + '/research-requests/' + entry['key'], params={'kind': kind})
            if response.status_code == 404:
                return None
            value = self.check(response).json()
            if kind == 'finding':
                return self.get(self.base + '/research-findings/' + value['set_id'] + '/versions/' + value['id'])
            return self.get(self.base + {'figure': '/research-figures/', 'report': '/research-reports/', 'candidate': '/research-manuscript-candidates/'}[kind] + value['id'])
        return self.ledger.post(label, path, body, send or (lambda e: self.check(self.client.post(path, json=e['body'], headers={'Idempotency-Key': e['key']})).json()), recover)

    def wait(self, task_id):
        start, previous = time.monotonic(), None
        while time.monotonic() - start < self.args.wait_seconds:
            task = self.get('/api/v1/tasks/' + task_id)
            status = task['status']
            if previous != status:
                print(json.dumps(dict(task_id=task_id, status=status)), flush=True)
                previous = status
            if status == 'succeeded':
                return task
            if status not in ('queued', 'running'):
                raise RuntimeError('Task stopped; retained original task: ' + task_id + ' / ' + str(task.get('error_code') or status))
            time.sleep(3)
        raise RuntimeError('Bounded observation ended; original task retained, no resubmission')

    def protected_snapshot(self):
        """Hash all pre-existing manuscript versions/exports and school binding rows."""
        from app.db.database import database_connection
        queries = {
            'manuscripts': 'SELECT * FROM manuscripts WHERE project_id=%s AND user_id=%s',
            'manuscript_versions': 'SELECT * FROM manuscript_versions WHERE project_id=%s AND user_id=%s',
            'manuscript_exports': 'SELECT e.* FROM manuscript_exports e JOIN manuscript_versions v ON v.id=e.version_id WHERE v.project_id=%s AND v.user_id=%s',
            'thesis_profiles': 'SELECT *,project_id AS id FROM thesis_profiles WHERE project_id=%s AND user_id=%s',
            'school_template_confirmations': 'SELECT * FROM school_template_confirmations WHERE project_id=%s AND user_id=%s',
        }
        with database_connection() as db:
            return {name: {row['id']: digest(dict(row)) for row in db.execute(sql, (self.args.project_id, self.owner))} for name, sql in queries.items()}

    def prepare_sources(self):
        sources, results, sentinels = [], [], []
        for identifier in list(dict.fromkeys(self.args.result_id + self.args.figure_result_id)):
            result = self.get(self.base + '/bio-insight-results/' + identifier)
            if result['id'] != identifier or result['task']['status'] != 'succeeded':
                raise ValueError('Explicit result is not a published fixed version')
            self.write_json('sources/' + identifier + '/result.json', result)
            results.append(result)
            sources.append(dict(source_kind='bio_insight_result_version', source_id=identifier,
                                sha256=result['manifest_sha256'], locator={'kind': 'object'}))
            seen = set()
            for member in result['members']:
                if member['role'] == 'input_snapshot' or member['format'] not in ('tsv', 'csv'):
                    continue
                raw = self.bytes(member, self.output / 'sources' / identifier)
                columns, rows = literal_rows(raw, member['format'])
                self.source_tables[member['id']] = dict(columns=columns, rows=rows, sha256=member['sha256'], key=member['key'])
                if 'row_key' not in columns:
                    continue
                key_index = columns.index('row_key')
                for row in rows:
                    for index, value in enumerate(row):
                        tag = literal_tag(value)
                        if tag is None or tag in seen or columns[index] in ('row_key', 'feature_id', 'contrast_id'):
                            continue
                        seen.add(tag)
                        selected = dict(source_kind='bio_insight_result_member', source_id=member['id'], sha256=member['sha256'],
                            locator=dict(kind='row', table=member['key'], row_key={'row_key': row[key_index]}, column=columns[index]))
                        sources.append(selected)
                        sentinels.append(dict(source=selected, literal_value=value, literal_category=tag, result_id=identifier))
                    if seen == {'zero', 'NA'}:
                        break
        self.record['source_inventory'] = [dict(id=r['id'], kind=r['kind'], inference_scope=r['inference_scope'], provenance=r['provenance'], manifest_sha256=r['manifest_sha256']) for r in results]
        self.record['literal_sentinels'] = sentinels
        self.ledger.save()
        return sources, results

    def finding(self, sources):
        preview = self.check(self.client.post(self.base + '/research-results/preview', json={'sources': sources})).json()
        self.write_json('source-preview.json', preview)
        facts = [fact for catalog in preview['catalogs'] for fact in catalog['facts']]
        # Freeze a bounded, meaningful sample of facts; reports still export full member tables.
        selected = list(dict.fromkeys(f['id'] for f in sorted(facts, key=lambda f: f['source_kind'] != 'bio_insight_result_member')))[:500]
        body = dict(title='CR-B04 固定差异／富集／候选工程核对', sources=sources, selected_fact_ids=selected,
                    notes='CR-B04 downstream engineering acceptance. Source provenance/units/limitations retained; no biological validation or real model calls.')
        value = self.post('finding', self.base + '/research-findings', body, kind='finding')
        self.write_json('finding.json', value)
        for sentinel in self.record['literal_sentinels']:
            match = [f for f in value['content']['facts'] if f['source_id'] == sentinel['source']['source_id'] and f['locator']['row_key'] == sentinel['source']['locator']['row_key'] and f['locator'].get('column') == sentinel['source']['locator']['column']]
            if not match or str(match[0]['raw_value']) != sentinel['literal_value'] or match[0]['source_sha256'] != sentinel['source']['sha256']:
                raise AssertionError('Literal 0/NA fact or source SHA changed')
        return value

    def research_figure(self, results):
        figures = [r for r in results if r['id'] in self.args.figure_result_id]
        if not figures:
            return None
        panels = []
        for i, result in enumerate(figures):
            if result['kind'] != 'figure':
                raise ValueError('--figure-result-id must identify a figure result')
            member = next(m for m in result['members'] if m['format'] == 'png' and m['role'] != 'input_snapshot')
            panels.append(dict(source=dict(source_kind='bio_insight_result_member', source_id=member['id'], sha256=member['sha256'], locator={'kind': 'image'}), label=chr(65 + i)))
        body = dict(mode='reuse' if len(panels) == 1 else 'composite', panels=panels, title='CR-B04 fixed result figures',
                    caption='Engineering downstream check; inference scopes and original q/units remain as recorded. Not biological validation.',
                    language='en', figure_language='original', formats=['png', 'tiff', 'svg', 'pdf'], columns=min(3, len(panels)))
        value = self.post('research-figure', self.base + '/research-figures', body, kind='figure')
        self.wait(value['task_id'])
        value = self.get(self.base + '/research-figures/' + value['id'])
        for member in value['members']:
            self.bytes(member, self.output / 'research-figure')
        return value

    def pdf(self, label, source_kind, source_id, expected_sha, folder):
        old = self.record['actions'].get(label)
        body = old['body'] if old else dict(source_kind=source_kind, source_id=source_id, request_key='b04-pdf-' + uuid4().hex)
        def recover(entry):
            identity = self.lookup_sql('pdf_exports', 'request_key', entry['body']['request_key'])
            return self.get(self.base + '/pdf-exports/' + identity) if identity else None
        value = self.post(label, self.base + '/pdf-exports', body, recovery=recover)
        self.wait(value['task_id'])
        value = self.get(self.base + '/pdf-exports/' + value['id'])
        if value['source_id'] != source_id or value['source_kind'] != source_kind or value['source_sha256'] != expected_sha:
            raise AssertionError('PDF source DOCX binding differs')
        raw = self.bytes(dict(value, key='analysis', format='pdf'), folder)
        if not raw.startswith(b'%PDF-'):
            raise AssertionError('Not a PDF')
        import pdfplumber
        with pdfplumber.open(io.BytesIO(raw)) as document:
            if not document.pages:
                raise AssertionError('PDF contains no pages')
            pages = [dict(page=i + 1, width=p.width, height=p.height, extracted_characters=len(p.extract_text() or '')) for i, p in enumerate(document.pages)]
        self.write_json(str(folder.relative_to(self.output) / 'pdf.json'), dict(value, structural_pages=pages, visual_review='not_performed'))
        return value

    def report(self, language, finding, figure):
        label = 'report-' + language
        body = dict(title='CR-B04 差异富集与候选分析工程报告' if language == 'zh-CN' else 'CR-B04 differential enrichment and candidate engineering report',
                    language=language, finding_version_id=finding['id'], figure_version_ids=[figure['id']] if figure else [])
        value = self.post(label, self.base + '/research-reports', body, kind='report')
        self.wait(value['task_id'])
        value = self.get(self.base + '/research-reports/' + value['id'])
        folder = self.output / language
        raws = self.report_members(value, folder)
        counts = value['manifest']['row_counts']
        checked = verify_workbook(raws['xlsx'], counts, self.source_tables)
        with zipfile.ZipFile(io.BytesIO(raws['zip'])) as archive:
            if archive.read('results.xlsx') != raws['xlsx'] or archive.read('analysis.docx') != raws['docx']:
                raise AssertionError('ZIP does not contain the exact report files')
            for i, table in enumerate(value['content']['tables']):
                if sha(archive.read(f'tables/table_{i:03d}.tsv')) != table['sha256']:
                    raise AssertionError('Full raw table missing or changed in ZIP')
        self.write_json(language + '/report.json', value)
        self.write_json(language + '/table-verification.json', checked)
        docx = next(m for m in value['members'] if m['role'] == 'docx')
        pdf = self.pdf('report-pdf-' + language, 'research_report', docx['id'], docx['sha256'], folder)
        packaged = self.post('package-with-pdf-' + language, self.base + '/research-reports',
            dict(body, root_id=value['root_id'], expected_revision=value['revision'], include_pdf_id=pdf['id']), kind='report')
        self.wait(packaged['task_id'])
        packaged = self.get(self.base + '/research-reports/' + packaged['id'])
        packed = next(m for m in packaged['members'] if m['role'] == 'zip')
        with zipfile.ZipFile(io.BytesIO(self.bytes(packed, folder / 'with-pdf'))) as archive:
            if sha(archive.read('analysis.pdf')) != pdf['sha256']:
                raise AssertionError('Explicit PDF package binding differs')
        return value, pdf, packaged

    def deliveries(self):
        intake = self.get(self.base + '/research-intake')
        active = {d['kind']: d['id'] for d in intake['deliveries'] if d['active']}
        if not {'sci_draft', 'thesis_draft'} <= set(active):
            old = self.record['actions'].get('enable-writing-services')
            if old:
                body = old['body']
            else:
                current = intake['current_requirement']
                content = dict(current['content']) if current else {'schema_version': 1}
                content['services'] = list(dict.fromkeys(content.get('services', []) + ['analysis', 'sci_draft', 'thesis_draft']))
                content['notes'] = content.get('notes', '') + '\nCR-B04 isolated copy: independent engineering manuscript roots; existing manuscripts retained.'
                keys = ('delivery_id', 'file_id', 'bio_dataset_version_id', 'locator', 'availability', 'purpose', 'note')
                refs = [{k: r[k] for k in keys if k in r} for r in (current.get('material_refs', []) if current else [])]
                body = dict(expected_revision=intake['revision'], operation='save', content=content, material_refs=refs)
            def recover(entry):
                response = self.client.get(self.base + '/requirements/requests/' + entry['key'])
                return None if response.status_code == 404 else self.check(response).json()
            self.post('enable-writing-services', self.base + '/requirements', body, recovery=recover)
        result = {d['kind']: d['id'] for d in self.get(self.base + '/deliveries')['items'] if d['active']}
        if not {'sci_draft', 'thesis_draft'} <= set(result):
            raise ValueError('Explicit writing services were not enabled')
        self.record['writing_deliveries'] = dict(ids={k: result[k] for k in ('sci_draft', 'thesis_draft')},
            mode='existing unique service registrations; new independent manuscript roots, never old-root revisions')
        self.ledger.save()
        return result

    def thesis_selection(self):
        profile = self.get(self.base + '/thesis-profile')
        if self.record.get('thesis_selection'):
            selection = self.record['thesis_selection']
        elif self.args.thesis_selection:
            selection = json.loads(self.args.thesis_selection.read_text(encoding='utf-8-sig'))
        else:
            selection = None
            for manuscript in self.get(self.base + '/manuscripts')['items']:
                version = self.get(self.base + '/manuscripts/' + manuscript['id'] + '/versions/' + str(manuscript['current_revision']))
                thesis = version.get('input', {}).get('thesis')
                if thesis and thesis['confirmation_id'] == profile['bound_confirmation_id'] and thesis['profile_revision'] == profile['revision']:
                    selection = thesis
                    self.record['school_mapping_origin'] = dict(manuscript_id=manuscript['id'], version_id=version['id'], mode='reuse frozen explicit mapping, no profile/binding changes')
                    break
        if not selection:
            raise ValueError('No matching frozen school mapping. Supply --thesis-selection JSON with actual confirmation/profile/chapter mapping; this helper never changes an existing school profile or binding')
        if selection['confirmation_id'] != profile['bound_confirmation_id'] or selection['profile_revision'] != profile['revision']:
            raise ValueError('School mapping does not match the existing exact profile binding')
        self.record['thesis_selection'] = selection
        self.ledger.save()
        return selection

    def writing(self, finding, figure, reports):
        deliveries, thesis = self.deliveries(), self.thesis_selection()
        published = []
        for kind in ('sci_draft', 'thesis_draft'):
            language = 'en' if kind == 'sci_draft' else 'zh-CN'
            report = reports[language]
            body = dict(delivery_id=deliveries[kind], manuscript_id=None, expected_revision=0, base_version_id=None,
                finding_version_ids=[finding['id']], figure_version_ids=[figure['id']] if figure else [], report_version_ids=[report['id']],
                output_language=language, sections=['results', 'materials_and_methods'],
                manual_notes='CR-B04 engineering acceptance: fixed analysis provenance and inference limits retained. New manuscript root only; no paid model or biological validation.')
            if kind == 'thesis_draft':
                body['thesis'] = thesis
            preview = self.check(self.client.post(self.base + '/research-results/writing-selection', json=body)).json()
            if preview['real_model_calls'] is not False or preview['writing_scope'] != 'results_methods':
                raise AssertionError('Unexpected writing scope or model path')
            self.write_json(kind + '/selection-preview.json', preview)
            candidate = self.post('candidate-' + kind, self.base + '/research-manuscript-candidates', body, kind='candidate')
            self.wait(candidate['task_id'])
            candidate = self.get(self.base + '/research-manuscript-candidates/' + candidate['id'])
            if candidate['candidate']['writing_scope'] != 'results_methods' or candidate['manuscript_id'] is not None or candidate['expected_revision'] != 0:
                raise AssertionError('Candidate unexpectedly targets an old manuscript')
            self.write_json(kind + '/candidate.json', {k: candidate[k] for k in ('id', 'delivery_id', 'candidate_sha256', 'candidate')})
            if not self.args.publish:
                continue
            frozen = self.record.setdefault('explicit_publications', {}).setdefault(kind, dict(candidate_id=candidate['id'], candidate_sha256=candidate['candidate_sha256'], scope='explicit --publish for engineering new root; no human content/Word visual acceptance claimed'))
            if frozen['candidate_id'] != candidate['id'] or frozen['candidate_sha256'] != candidate['candidate_sha256']:
                raise AssertionError('Exact candidate changed before explicit publication')
            self.ledger.save()
            def recover_publish(_entry):
                current = self.get(self.base + '/research-manuscript-candidates/' + candidate['id'])
                if not current['published_version_id']:
                    return None
                for root in self.get(self.base + '/manuscripts')['items']:
                    version = self.get(self.base + '/manuscripts/' + root['id'] + '/versions/1')
                    if version['id'] == current['published_version_id']:
                        return dict(manuscript_id=root['id'], version_id=version['id'], revision=1, candidate_id=candidate['id'])
                raise RuntimeError('Published candidate could not be matched to an actual public manuscript')
            result = self.post('publish-' + kind, self.base + '/research-manuscript-candidates/' + candidate['id'] + '/publish',
                dict(candidate_id=candidate['id'], expected_revision=0), recovery=recover_publish)
            if result['manuscript_id'] in self.record['protected_before']['manuscripts']:
                raise AssertionError('Publication reused a protected old manuscript')
            endpoint = self.base + '/manuscripts/' + result['manuscript_id']
            version = self.get(endpoint + '/versions/1')
            self.write_json(kind + '/published-version.json', version)
            materials = self.get(endpoint + '/versions/1/writing-materials')
            self.write_json(kind + '/writing-materials.json', materials)
            options = {} if kind == 'sci_draft' else (json.loads(self.args.school_export_options.read_text(encoding='utf-8-sig')) if self.args.school_export_options else {'school': {'include_toc': False}})
            def recover_export(entry):
                identity = self.lookup_sql('manuscript_exports', 'idempotency_key', entry['key'], version=result['version_id'])
                return self.get(endpoint + '/exports/' + identity) if identity else None
            export = self.post('manuscript-docx-' + kind, endpoint + '/versions/1/exports', options, recovery=recover_export)
            self.wait(export['task_id'])
            export = self.get(endpoint + '/exports/' + export['id'])
            self.bytes(dict(export, key='analysis', format='docx'), self.output / kind)
            pdf = self.pdf('manuscript-pdf-' + kind, 'manuscript_export', export['id'], export['sha256'], self.output / kind)
            published.append(dict(kind=kind, delivery_id=deliveries[kind], **result, docx_export_id=export['id'], pdf_id=pdf['id']))
        self.record['published'] = published

    def run(self):
        if self.get(self.base)['project_type'] != 'research':
            raise ValueError('Use the explicit B04 research project containing these results')
        if 'protected_before' not in self.record:
            self.record['protected_before'] = self.protected_snapshot()
            self.ledger.save()
        # Resolve an already confirmed mapping before creating any downstream
        # artifact. A missing or stale binding is an explicit setup boundary.
        self.thesis_selection()
        sources, results = self.prepare_sources()
        finding = self.finding(sources)
        figure = self.research_figure(results)
        reports = {}
        self.record['reports'] = {}
        for language in ('zh-CN', 'en'):
            report, pdf, packaged = self.report(language, finding, figure)
            reports[language] = report
            self.record['reports'][language] = dict(report_version_id=report['id'], pdf_id=pdf['id'], packaged_report_version_id=packaged['id'])
            self.ledger.save()
        self.writing(finding, figure, reports)
        after = self.protected_snapshot()
        for table, rows in self.record['protected_before'].items():
            for identity, expected in rows.items():
                if after[table].get(identity) != expected:
                    raise AssertionError('Protected prior material changed: ' + table + '/' + identity)
        for source in results:
            current = self.get(self.base + '/bio-insight-results/' + source['id'])
            if current['manifest_sha256'] != source['manifest_sha256']:
                raise AssertionError('Original B04 result changed')
        self.record.update(finding_version_id=finding['id'], research_figure_version_id=figure['id'] if figure else None,
            protected_prior_materials_unchanged=True, original_result_hashes_unchanged=True,
            status='api_engineering_chain_complete' if self.args.publish else 'candidates_ready_explicit_publication_pending',
            word_visual_review='not_performed', user_acceptance='pending', biological_validation='not_performed', real_model_calls=0)
        self.ledger.save()


def self_test():
    """Offline engineering checks; no application imports, API, DB or services."""
    import tempfile
    from openpyxl import Workbook
    with tempfile.TemporaryDirectory(prefix='b04-downstream-self-test-') as temporary:
        ledger = Ledger(Path(temporary) / 'receipt.json', {'schema': 'synthetic'})
        calls = []
        def unknown(entry):
            calls.append(entry.copy())
            raise TimeoutError('synthetic unknown')
        try:
            ledger.post('a', '/local', {'value': 0}, unknown, lambda _: None)
        except TimeoutError:
            pass
        try:
            ledger.post('a', '/local', {'value': 0}, unknown, lambda _: None)
            raise AssertionError('Unknown should never blindly repost')
        except RuntimeError:
            pass
        assert len(calls) == 1
        restored = Ledger(Path(temporary) / 'receipt.json', {'schema': 'synthetic'}, ['a'])
        result = restored.post('a', '/local', {'value': 0}, lambda e: {'id': e['key']}, lambda _: None)
        assert result['id'] == calls[0]['key'] and restored.record['actions']['a']['body'] == {'value': 0}
        raw = b'row_key\tvalue\nr0\t0\nr1\tNA\n'
        columns, rows = literal_rows(raw, 'tsv')
        book = Workbook()
        sheet = book.active
        sheet.title = 'results'
        sheet.append(columns)
        for row in rows:
            sheet.append(row)
        stream = io.BytesIO()
        book.save(stream)
        book.close()
        counts = {'tables': [dict(source={'source_id': 'member1'}, sha256=sha(raw), rows=2, sheets=['results'])]}
        checked = verify_workbook(stream.getvalue(), counts, {'member1': dict(columns=columns, rows=rows, sha256=sha(raw))})
        assert checked[0]['raw_zero_cells'] == 1 and checked[0]['raw_NA_cells'] == 1
        # Exercise the actual request models without a DB, queue or HTTP call.
        from app.domain.research_results.contracts import FindingVersionRequest, ResearchFigureRequest, ResearchReportRequest, ResearchCandidateRequest, ResearchPublishRequest
        from app.domain.pdf_exports.contracts import PdfCreateRequest
        from app.domain.manuscripts.contracts import ExportRequest
        source = dict(source_kind='bio_insight_result_member', source_id='synthetic-member', sha256='a' * 64,
                      locator=dict(kind='row', table='comparison_results', row_key={'row_key': 'r0'}, column='original_q'))
        FindingVersionRequest.model_validate(dict(title='Synthetic engineering facts', sources=[source]))
        ResearchFigureRequest.model_validate(dict(mode='reuse', panels=[dict(source=dict(source_kind='bio_insight_result_member', source_id='synthetic-image', sha256='b' * 64, locator={'kind': 'image'}))]))
        ResearchReportRequest.model_validate(dict(title='Synthetic report', finding_version_id='finding1', language='en'))
        ResearchCandidateRequest.model_validate(dict(delivery_id='delivery1', manuscript_id=None, expected_revision=0, base_version_id=None, finding_version_ids=['finding1'], output_language='en', sections=['results', 'materials_and_methods']))
        ResearchPublishRequest.model_validate(dict(candidate_id='candidate1', expected_revision=0))
        PdfCreateRequest.model_validate(dict(source_kind='research_report', source_id='member1', request_key='synthetic-request-key'))
        ExportRequest.model_validate({'school': {'include_toc': False}})
    print(json.dumps(dict(offline_self_test='passed', checks=['unknown_get_first_no_repost', 'explicit_retry_same_key_body', 'complete_rows_literal_zero_NA', 'seven_actual_request_models']), ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path)
    parser.add_argument('--project-id')
    parser.add_argument('--result-id', action='append', default=[])
    parser.add_argument('--figure-result-id', action='append', default=[])
    parser.add_argument('--thesis-selection', type=Path, help='Optional exact existing confirmation/profile/chapter selection JSON; existing bindings are never modified')
    parser.add_argument('--school-export-options', type=Path, help='Optional explicit ExportRequest JSON for the new school DOCX only; no existing export input is modified')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--publish', action='store_true', help='Explicitly publish only the newly created engineering candidates as new manuscript roots')
    parser.add_argument('--retry-original', action='append', default=[], metavar='ACTION_LABEL')
    parser.add_argument('--wait-seconds', type=int, default=14400,
                        help='Per-task observation window, 60..14400 seconds; expiry preserves the original task')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if not args.state or not args.project_id or not args.result_id or len(args.result_id) > 10 or len(args.figure_result_id) > 6:
        parser.error('Supply explicit --state, --project-id, 1–10 --result-id and at most 6 --figure-result-id')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value) for value in [args.project_id, *args.result_id, *args.figure_result_id]):
        parser.error('Invalid explicit identity')
    if args.publish and not args.execute:
        parser.error('--publish requires --execute')
    import cr_b04_runner as control
    control.STATE = args.state.resolve()
    state = control.read_state()
    if state['clone_status'] != 'verified' or state['schema'] == state['source_schema'] or not 60 <= args.wait_seconds <= 14400:
        raise ValueError('Verified B04 copy and bounded wait are required')
    token = digest(dict(project=args.project_id, results=args.result_id, figures=args.figure_result_id))[:12]
    output = (args.output or (control.RUNTIME / 'downstream' / token)).resolve()
    if not output.is_relative_to(control.RUNTIME.resolve()) or output == control.RUNTIME.resolve():
        raise ValueError('Evidence output must be a dedicated directory inside the B04 runtime')
    if not args.execute:
        print(json.dumps(dict(mode='offline_prepared_not_executed', schema=state['schema'], project_id=args.project_id,
            result_ids=args.result_id, figure_result_ids=args.figure_result_id, output=str(output),
            chain=['fixed sources and literal rows', 'finding', 'ZH/EN complete XLSX/ZIP/DOCX', 'exact-source report PDFs',
                   'new SCI/thesis candidates', 'separate --publish gate', 'new-root DOCX/PDF'],
            existing_school_binding='reuse only; provide --thesis-selection if no matching prior frozen selection'), ensure_ascii=False, indent=2))
        return
    control.configure(state)
    run = Acceptance(args, state, output)
    try:
        run.run()
        print(json.dumps(dict(status=run.record['status'], receipt=str(run.ledger.path), finding_version_id=run.record['finding_version_id'], published=run.record.get('published', [])), ensure_ascii=False))
    finally:
        run.client.close()


if __name__ == '__main__':
    main()
