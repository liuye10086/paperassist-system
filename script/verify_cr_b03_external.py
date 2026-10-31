"""Retained, resumable external-result engineering example. No biological data."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'script/dev'), str(ROOT / 'backend')]
import cr_b03_runner as control


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def materials():
    directory = control.RUNTIME / 'external-materials'
    directory.mkdir(exist_ok=True)
    xlsx = directory / 'synthetic-external-results.xlsx'
    if not xlsx.exists():
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.title = 'Results'
        sheet.append(['gene_id_text', 'external_value', 'declaration'])
        sheet.append(['ENSG_SYNTHETIC_000001', 0, 'Synthetic external result not recalculated'])
        sheet.append(['000002_SYNTHETIC', 'NA', 'NA is a text label, not numeric zero'])
        sheet['A2'].number_format = '@'
        sheet['A3'].number_format = '@'
        sheet.append(['SYNTHETIC_ONLY', None, 'Not biological evidence; no donor replication'])
        book.save(xlsx)
        book.close()
    pdf = directory / 'synthetic-external-result.pdf'
    if not pdf.exists():
        import pypdfium2 as pdfium
        document = pdfium.PdfDocument.new()
        page = document.new_page(612, 792)
        lines = ['SYNTHETIC EXTERNAL RESULT - ENGINEERING FIXTURE',
                 'Synthetic external result not recalculated',
                 'This page is a synthetic provenance and page-locator example.',
                 'The workbook records numeric zero and the literal text NA separately.',
                 'No biological measurements, clinical claims, or donor replicates.',
                 'The illustration is a synthetic layout asset, not a scientific result.']
        for index, line in enumerate(lines):
            obj = pdfium.raw.FPDFPageObj_NewTextObj(document.raw, b'Helvetica', 11)
            encoded = line.encode('utf-16-le') + b'\0\0'
            buffer = (ctypes.c_ushort * (len(encoded) // 2)).from_buffer_copy(encoded)
            if not obj or not pdfium.raw.FPDFText_SetText(obj, buffer):
                raise RuntimeError('Could not create synthetic PDF text')
            pdfium.raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 40, 735 - index * 28)
            pdfium.raw.FPDFPage_InsertObject(page.raw, obj)
        page.gen_content()
        document.save(pdf)
        page.close()
        document.close()
    png = directory / 'synthetic-external-illustration.png'
    if not png.exists():
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (960, 540), '#f5f7fa')
        drawing = ImageDraw.Draw(image)
        drawing.text((35, 30), 'SYNTHETIC EXTERNAL ILLUSTRATION', fill='#1d3557', font_size=27)
        drawing.rectangle((70, 120, 400, 380), outline='#457b9d', width=5)
        drawing.ellipse((520, 120, 850, 380), outline='#e76f51', width=5)
        drawing.text((80, 425), 'Layout example only - not scientific data', fill='#1d3557', font_size=25)
        drawing.text((80, 470), 'External result not recalculated; no biological validation', fill='#1d3557', font_size=20)
        image.save(png, dpi=(150, 150))
    import pypdfium2 as pdfium
    with pdfium.PdfDocument(pdf) as document:
        if len(document) != 1:
            raise ValueError('External PDF must have one page')
        text = document[0].get_textpage().get_text_range()
        if 'Synthetic external result not recalculated' not in text:
            raise ValueError('Synthetic PDF declaration missing')
    return [xlsx, pdf, png]


class ExternalVerification:
    def __init__(self, retry_original=False):
        import httpx
        self.state = control.read_state()
        control.configure(self.state)
        self.path = control.RUNTIME / 'external-receipt.json'
        self.record = json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else dict(
            schema=self.state['schema'], actions={}, synthetic=True, real_model_calls=0,
            external_results_recomputed=False, biological_validation='not_performed', user_acceptance='pending')
        if self.record['schema'] != self.state['schema']:
            raise ValueError('External receipt belongs to another isolated schema')
        self.retry_original = retry_original
        self.client = httpx.Client(base_url=self.state['url'], timeout=600, trust_env=False,
                                  headers={'Origin': self.state['url'], 'X-PaperAssist-Client': 'web'})
        credential = json.loads((Path(self.state['assets']).parent / 'credentials.json').read_text(encoding='utf-8-sig'))['review']
        result = self.check(self.client.post('/api/v1/auth/login', json={k: credential[k] for k in ('email', 'password')})).json()
        self.client.headers['X-CSRF-Token'] = result['csrf_token']

    def save(self):
        control.worker_stack.private_write(self.path, json.dumps(self.record, ensure_ascii=False, indent=2))

    @staticmethod
    def check(response):
        if response.status_code not in (200, 201, 202):
            try:
                code = response.json()['detail']['code']
            except (ValueError, KeyError, TypeError):
                code = 'unexpected_response'
            raise RuntimeError(f'HTTP {response.status_code}: {code}')
        return response

    def get(self, path):
        return self.check(self.client.get(path)).json()

    def post(self, label, path, body, recover):
        digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        action = self.record['actions'].get(label)
        if action:
            if action['digest'] != digest or action['path'] != path:
                raise ValueError('Original external request intent differs; retained unchanged')
            if 'response' in action:
                return action['response']
            recovered = recover(action)
            action['recovery_read_at'] = time.time()
            self.save()
            if recovered is not None:
                action.update(response=recovered, status='recovered')
                self.save()
                return recovered
            if not self.retry_original:
                raise RuntimeError('Original request not found after read. Explicit --retry-original is required; original key/body retained')
        else:
            action = dict(key='b03-external-' + uuid4().hex, path=path, body=body, digest=digest, status='submitting')
            self.record['actions'][label] = action
            self.save()
        result = self.check(self.client.post(path, json=action['body'], headers={'Idempotency-Key': action['key']})).json()
        action.update(response=result, status='returned')
        self.save()
        return result

    def optional(self, path):
        response = self.client.get(path)
        if response.status_code == 404:
            return None
        return self.check(response).json()

    def recover_batch(self, body):
        ids = {item['client_id'] for item in body['items']}
        page = 1
        while True:
            result = self.get(self.base + f'/file-batches?page={page}&page_size=100')
            for batch in result['items']:
                if {item['id'] for item in batch['items']} == ids:
                    return batch
            if page * result['page_size'] >= result['total']:
                return None
            page += 1

    def upload(self, batch, item, path):
        label = 'upload-' + item['id']
        action = self.record['actions'].get(label)
        current = next(v for v in self.get(self.base + '/file-batches/' + batch['id'])['items'] if v['id'] == item['id'])
        if current['file_id']:
            if action is None:
                raise ValueError('File exists without this retained external upload identity')
            if action['sha256'] != sha(path):
                raise ValueError('Retained external original differs')
            action.update(response=current, status='recovered')
            self.save()
            return current
        if action and not self.retry_original:
            action['recovery_read_at'] = time.time()
            self.save()
            raise RuntimeError('Original upload remains unconfirmed after GET. Use --retry-original for this same item and bytes')
        if action is None:
            action = dict(path=str(path), sha256=sha(path), item_id=item['id'], status='submitting')
            self.record['actions'][label] = action
            self.save()
        if action['sha256'] != sha(path):
            raise ValueError('External original changed; upload not retried')
        with path.open('rb') as source:
            result = self.check(self.client.post(self.base + '/file-batches/' + batch['id'] + '/items/' + item['id'],
                                                files={'file': (path.name, source, 'application/octet-stream')})).json()
        action.update(response=result, status='returned')
        self.save()
        return result

    def run(self):
        files = materials()
        self.record['materials'] = [dict(path=str(p), filename=p.name, sha256=sha(p), size_bytes=p.stat().st_size) for p in files]
        self.save()
        project = self.post('project', '/api/v1/projects', dict(name='CR-B03 外部结果核对（合成）',
            research_topic='合成工程材料：零与文本NA、原始XLSX定位、PDF页码和PNG来源；不重新计算外部结果，不代表生物学。',
            project_type='research', delivery_kinds=['analysis']), lambda action: self.optional('/api/v1/project-create-requests/' + action['key']))
        self.record['project_id'] = project['id']
        self.base = '/api/v1/projects/' + project['id']
        old = self.record['actions'].get('batch')
        body = old['body'] if old else dict(items=[dict(client_id=str(uuid4()), filename=p.name, size_bytes=p.stat().st_size) for p in files])
        batch = self.post('batch', self.base + '/file-batches', body, lambda action: self.recover_batch(action['body']))
        for item, path in zip(batch['items'], files):
            self.upload(batch, item, path)
        start = time.monotonic()
        while True:
            current = self.get(self.base + '/file-batches/' + batch['id'])
            self.record['batch'] = current
            self.save()
            states = [item['status'] for item in current['items']]
            if all(status in ('parsed', 'stored', 'failed') for status in states):
                break
            if time.monotonic() - start > 1200:
                raise RuntimeError('External parse wait timed out; materials and pending identities retained')
            time.sleep(3)
        by_name = {v['filename']: v for v in current['items']}
        xlsx, pdf, png = [by_name[p.name] for p in files]
        if xlsx['status'] != 'parsed' or pdf['status'] != 'parsed':
            raise RuntimeError('Required external XLSX/PDF parsing failed; exact statuses retained in external receipt')
        pdf_versions = self.get(self.base + '/files/' + pdf['file_id'] + '/document-versions')['items']
        parse_id = next(v['id'] for v in pdf_versions if v['status'] == 'succeeded')
        pdf_pages = self.get(self.base + '/files/' + pdf['file_id'] + '/document-versions/' + parse_id + '/pages?page=1')
        self.record.update(pdf_document_version_id=parse_id, pdf_pages=pdf_pages)
        sources = [dict(source_kind='original_file', source_id=xlsx['file_id'], sha256=sha(files[0]), locator=dict(kind='cell', sheet='Results', cell=cell)) for cell in ('B2', 'B3')]
        sources += [dict(source_kind='original_file', source_id=pdf['file_id'], sha256=sha(files[1]), locator=dict(kind='page', page=1, parse_version_id=parse_id)),
                    dict(source_kind='original_file', source_id=png['file_id'], sha256=sha(files[2]), locator=dict(kind='image'))]
        preview = self.check(self.client.post(self.base + '/research-results/preview', json=dict(sources=sources))).json()
        facts = [fact for catalog in preview['catalogs'] for fact in catalog['facts']]
        assert len(facts) == 2 and facts[0]['raw_value'] == 0 and facts[1]['raw_value'] == 'NA'
        assert all(f['origin'] == 'external_result' and f['verification_status'] == 'unverified' for f in facts)
        self.record['preview'] = preview
        self.save()
        def recover_finding(action):
            found = self.optional(self.base + '/research-requests/' + action['key'] + '?kind=finding')
            return self.get(self.base + '/research-findings/' + found['set_id'] + '/versions/' + found['id']) if found else None
        conflict = dict(id='synthetic-zero-versus-na', fact_ids=[f['id'] for f in facts],
                        note='合成工程冲突：显式数值0与文本NA必须保持不同，不能替换、求平均或伪称系统重算。', decision='unresolved', basis='')
        v1_body = dict(title='合成外部结果：零、文本NA与精确来源（未重算）', sources=sources, selected_fact_ids=[f['id'] for f in facts],
            conflicts=[conflict], claims=[], reviews=[], notes='Synthetic external result not recalculated。仅A04/A10工程核对；不存在生物学、临床或独立donor结论。')
        v1 = self.post('finding-v1', self.base + '/research-findings', v1_body, recover_finding)
        v2_body = dict(v1_body, set_id=v1['set_id'], expected_revision=v1['revision'],
            conflicts=[dict(conflict, decision='explained', basis='人工工程核对：0是数值零；NA是原始文本标签。解释类型差异，不更改原值，不补算外部结果。')],
            reviews=[dict(target_id=conflict['id'], decision='checked', basis='已核对原XLSX Results!B2/B3；仅确认定位与类型区别。', evidence=[])],
            notes=v1_body['notes'] + '\n人工核对版v2：保留原始XLSX/PDF/PNG和v1，记录冲突解释，不将unverified提升为verified。')
        v2 = self.post('finding-v2', self.base + '/research-findings/' + v1['set_id'] + '/versions', v2_body, recover_finding)
        historical = self.get(self.base + '/research-findings/' + v1['set_id'] + '/versions/' + v1['id'])
        assert historical['sha256'] == v1['sha256'] and historical['content']['conflicts'][0]['decision'] == 'unresolved'
        assert all(f['origin'] == 'external_result' and f['verification_status'] == 'unverified' for f in v2['content']['facts'])
        intake = self.get(self.base + '/research-intake')
        assert not any(d['active'] and d['kind'] != 'analysis' for d in intake['deliveries'])
        for item, path in zip(current['items'], files):
            assert sha(path) == next(m['sha256'] for m in self.record['materials'] if m['filename'] == path.name)
        self.record.update(status='verified_synthetic_external_example', finding_set_id=v1['set_id'],
            finding_version_ids=[v1['id'], v2['id']], historical_version_preserved=True, files={p.name: by_name[p.name]['file_id'] for p in files},
            source_files_unchanged=True, thesis_or_sci_delivery_activated=False,
            manual_checks=['A04: source locators, numeric zero and text NA remain distinct', 'A10: compare v1 unresolved conflict and v2 explanation/reviewer audit'],
            project_link=self.state['url'] + '/#project=' + project['id'] + '&section=analysis&view=research-findings')
        self.save()
        print(json.dumps({k: self.record[k] for k in ('status', 'project_id', 'files', 'pdf_document_version_id', 'finding_set_id', 'finding_version_ids')}, ensure_ascii=False), flush=True)
        print(str(self.path), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--retry-original', action='store_true', help='After recovery GET confirms absence, explicitly reuse the retained key and exact body')
    args = parser.parse_args()
    verification = ExternalVerification(args.retry_original)
    try:
        verification.run()
    finally:
        verification.client.close()


if __name__ == '__main__':
    main()
