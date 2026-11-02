"""Revise the affected PBMC report using a repaired figure and unchanged tables."""
import json
import shutil
import io
import zipfile
from copy import deepcopy
from uuid import uuid4
from verify_cr_b05_sub3_delivery import Acceptance, Delivery
from verify_cr_b05_sub2_delivery import ooxml_identity
import cr_b04_downstream as shared


class RepairDelivery(Delivery):
    def __init__(self, acceptance):
        super().__init__(acceptance, 'pbmc3k')
        old = self.output
        self.original_figure = json.loads((old/'figure.json').read_bytes())
        self.original_report = json.loads((old/'zh-CN/packaged-report.json').read_bytes())
        self.original_finding = json.loads((old/'finding.json').read_bytes())
        self.output = old.with_name('pbmc3k-render-fixed')
        self.output.mkdir(exist_ok=True)
        for name in ('source-tables', 'source-preview.json'):
            source = old/name; target = self.output/name
            if not target.exists():
                if source.is_dir(): shutil.copytree(source, target)
                else: shutil.copyfile(source, target)
        proof = self.output/'complete-table-cell-proof.json'
        if proof.exists() and 'figure_reference_update' not in json.loads(proof.read_bytes()):
            proof.rename(self.output/'original-complete-table-cell-proof.json')

    def key(self, label): return self.label+'-render-fixed-'+label

    def post(self, label, path, body, kind=None, recover=None):
        if label in ('figure', 'report-zh-CN'):
            original = self.original_figure if label == 'figure' else self.original_report
            body = dict(body, root_id=original['root_id'], expected_revision=original['revision'])
        return self.parent.post(self.key(label), path, body, self.project, kind, 'research', recover)

    def finding(self):
        _, fixed = self.formal_source(); self.freeze_tables(fixed)
        self.write_json('finding.json', self.original_finding)
        return self.original_finding

    def verify_report(self, value, folder):
        # The repair changes exactly the figure version and SHA in the Figures
        # sheet. Reuse the million-cell proof only after every other XML member
        # is byte-identical (apart from the existing core timestamp allowance).
        raw = self.report_members(value, folder)['xlsx']
        old = self.output.with_name('pbmc3k')
        prior = json.loads((old/'complete-table-cell-proof.json').read_bytes())
        current = ooxml_identity(raw)
        figure = json.loads((self.output/'figure.json').read_bytes())
        member = 'xl/worksheets/sheet4.xml'
        with zipfile.ZipFile(old/'zh-CN/results.xlsx') as archive:
            expected = archive.read(member)
        replacements = {}
        for field in ('id', 'manifest_sha256'):
            before = self.original_figure[field].encode(); after = figure[field].encode()
            assert expected.count(before) == 1, 'Expected figure field is not unique'
            expected = expected.replace(before, after)
            replacements[field] = dict(before=before.decode(), after=after.decode())
        expected_parts = dict(prior['ooxml']['parts'])
        expected_parts[member] = shared.sha(expected)
        assert current['parts'] == expected_parts, 'Unexpected workbook content change outside the two figure references'
        derived = deepcopy(prior)
        derived.update(xlsx_sha256=shared.sha(raw), ooxml=current,
                       validation_mode='unchanged_source_cells_reused_with_exact_figure_reference_update',
                       figure_reference_update=replacements,
                       original_xlsx_sha256=prior['xlsx_sha256'])
        if not (self.output/'complete-table-cell-proof.json').exists():
            self.write_json('complete-table-cell-proof.json', derived)
        return super().verify_report(value, folder)

    def pdf(self, language, docx):
        label = 'pdf-'+language; old = self.record['actions'].get(self.key(label))
        body = old['body'] if old else dict(source_kind='research_report', source_id=docx['id'], request_key='b05-pdf-'+uuid4().hex)
        def recover(entry):
            from app.db.database import database_connection
            with database_connection() as db:
                row = db.execute('SELECT id FROM pdf_exports WHERE project_id=%s AND user_id=%s AND request_key=%s', (self.project,self.owner,entry['body']['request_key'])).fetchone()
            return self.get(self.base+'/pdf-exports/'+row['id']) if row else None
        value = self.post(label, self.base+'/pdf-exports', body, recover=recover)
        self.parent.wait(value['task_id']); value = self.get(self.base+'/pdf-exports/'+value['id'])
        assert value['source_id'] == docx['id'] and value['source_sha256'] == docx['sha256']
        raw = self.bytes(dict(value,key='analysis',format='pdf'), self.output/language)
        assert raw.startswith(b'%PDF-')
        self.write_json(language+'/pdf.json', value)
        return value


if __name__ == '__main__':
    acceptance = Acceptance()
    try:
        delivery = RepairDelivery(acceptance)
        finding = delivery.finding(); figure = delivery.figure()
        report = delivery.report('zh-CN',finding,figure)
        print(json.dumps(dict(report_version_id=report['id'],visual=delivery.visual_preview()),ensure_ascii=False))
    finally: acceptance.client.close()
