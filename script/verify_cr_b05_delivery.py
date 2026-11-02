"""B05 findings, complete reports and PDF packages; never publishes manuscripts."""
import argparse
import io
import json
from pathlib import Path
import sys
from uuid import uuid4
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'script'),str(ROOT/'script/dev'),str(ROOT/'backend')]
from verify_cr_b05_acceptance import Acceptance,profiles
from cr_b05_evidence import exact_table_set,read_table
import cr_b04_downstream as shared


class Delivery:
    # Reuse the accepted bounded ZIP/OOXML and byte-identity checks, not its B04 workflow.
    bytes=shared.Acceptance.bytes
    write_json=shared.Acceptance.write_json
    report_members=shared.Acceptance.report_members

    def __init__(self,acceptance,label):
        self.parent=acceptance;self.label=label;self.state=acceptance.state;self.owner=acceptance.owner
        self.project=acceptance.record['paths'][label]['project_id'];self.base=acceptance.base(self.project)
        self.output=acceptance.output/'reports'/label;self.output.mkdir(parents=True,exist_ok=True)
        self.client=acceptance.client;self.record=acceptance.record;self.source_tables={}

    def check(self,response):return self.parent.check(response)
    def get(self,path):return self.parent.get(path)
    def post(self,label,path,body,kind=None,recover=None):
        return self.parent.post(self.label+'-delivery-'+label,path,body,self.project,kind,'research',recover)

    def source(self,suffix):
        record=self.record['results'][self.label+'-'+suffix]
        value=self.get(self.base+'/bio-insight-results/'+record['id'])
        if value['manifest_sha256']!=record['manifest_sha256']:raise ValueError('Fixed delivery source differs')
        return dict(source_kind='bio_insight_result_version',source_id=value['id'],sha256=value['manifest_sha256'],locator={'kind':'object'}),value

    def finding(self):
        comparison,result=self.source('comparison');candidate,_=self.source('candidates')
        sources=[comparison,candidate]
        rows=read_table(self.parent.output/'delivery'/(self.label+'-comparison')/'comparison_results.tsv')
        representative=next(r for r in sorted(rows,key=lambda r:r['feature_id']) if r['p_value'] not in ('','NA') and r['effect_value'] not in ('','NA'))
        member=next(m for m in result['members'] if m['key']=='comparison_results')
        columns=['effect_value','p_value','q_within_contrast','n_numerator','n_denominator']
        row_identity={k:representative[k] for k in ('row_key','feature_id','contrast_id')}
        sources.extend(dict(source_kind='bio_insight_result_member',source_id=member['id'],sha256=member['sha256'],locator=dict(kind='row',table='comparison_results',row_key=row_identity,column=column)) for column in columns)
        preview=self.check(self.client.post(self.base+'/research-results/preview',json={'sources':sources})).json()
        self.write_json('source-preview.json',preview)
        facts=[fact for catalog in preview['catalogs'] for fact in catalog['facts']]
        selected=list(dict.fromkeys(f['id'] for f in facts))[:500]
        if not selected:raise ValueError('No actual research facts projected')
        body=dict(title='CR-B05 '+self.label+' 定量比较与候选核对（特征可读）',sources=sources,selected_fact_ids=selected,
            notes='授权公开材料的实际流程验证。展示行按 feature_id 排序取首个可计算项，仅用于精确来源核对；完整表始终保留。完整结果、尺度、实际 n 和缺失限制见固定来源；不代表生物学验证或用户验收，不发布稿件。')
        value=self.post('finding',self.base+'/research-findings',body,'finding')
        self.write_json('finding.json',value)
        if any(f['observation_level'] in ('spot','region') for f in value['content']['facts']):raise AssertionError('Sample result projected as spatial observation')
        actual={f['locator']['column']:f['raw_value'] for f in value['content']['facts'] if f['source_id']==member['id']}
        assert actual=={c:representative[c] for c in columns},'Finding values differ from exact frozen result row'
        assert all(f['locator']['row_key']==row_identity for f in value['content']['facts'] if f['source_id']==member['id']),'Readable exact feature/contrast identity was lost'
        return value

    def figure(self):
        _,result=self.source('volcano')
        member=next(m for m in result['members'] if m['format']=='png' and m['role']!='input_snapshot')
        body=dict(mode='reuse',panels=[dict(source=dict(source_kind='bio_insight_result_member',source_id=member['id'],sha256=member['sha256'],locator={'kind':'image'}),label='A')],
            title='CR-B05 '+self.label,caption='固定定量比较。单位、方向、统计范围、缺失和实际样本量以来源 Methods 与完整表为准。',
            language='zh-CN',figure_language='original',formats=['png','tiff','svg','pdf'],columns=1)
        value=self.post('figure',self.base+'/research-figures',body,'figure');self.parent.wait(value['task_id'])
        value=self.get(self.base+'/research-figures/'+value['id'])
        for m in value['members']:self.bytes(m,self.output/'figure')
        self.write_json('figure.json',value);return value

    def table_sources(self,report):
        # Derive the required table universe from the two frozen finding sources,
        # independently of the report's own declarations (which may omit a whole table).
        if not self.source_tables:
            for suffix in ('comparison','candidates'):
                _,result=self.source(suffix)
                for member in result['members']:
                    if member['format'] not in ('tsv','csv'):continue
                    identity=member['id']
                    assert identity not in self.source_tables
                    raw=self.bytes(dict(member,key=identity),self.output/'source-tables')
                    columns,rows=shared.literal_rows(raw,member['format'])
                    self.source_tables[identity]=dict(sha256=member['sha256'],columns=columns,rows=rows)
        exact_table_set(report['content']['tables'],self.source_tables)
        exact_table_set(report['manifest']['row_counts']['tables'],self.source_tables)

    def verify_report(self,value,folder):
        raws=self.report_members(value,folder);self.table_sources(value)
        checked=shared.verify_workbook(raws['xlsx'],value['manifest']['row_counts'],self.source_tables)
        assert len(checked)==len(self.source_tables) and {c['source_id'] for c in checked}==set(self.source_tables)
        with zipfile.ZipFile(io.BytesIO(raws['zip'])) as archive:
            assert archive.read('results.xlsx')==raws['xlsx'] and archive.read('analysis.docx')==raws['docx']
            for i,table in enumerate(value['content']['tables']):assert shared.sha(archive.read(f'tables/table_{i:03d}.tsv'))==table['sha256']
        return raws,checked

    def pdf(self,language,docx):
        label='pdf-'+language;key=self.label+'-delivery-'+label;old=self.record['actions'].get(key)
        body=old['body'] if old else dict(source_kind='research_report',source_id=docx['id'],request_key='b05-pdf-'+uuid4().hex)
        def recover(entry):
            from app.db.database import database_connection
            with database_connection() as db:
                row=db.execute('SELECT id FROM pdf_exports WHERE project_id=%s AND user_id=%s AND request_key=%s',(self.project,self.owner,entry['body']['request_key'])).fetchone()
            return self.get(self.base+'/pdf-exports/'+row['id']) if row else None
        value=self.post(label,self.base+'/pdf-exports',body,recover=recover);self.parent.wait(value['task_id'])
        value=self.get(self.base+'/pdf-exports/'+value['id'])
        assert value['source_kind']=='research_report' and value['source_id']==docx['id'] and value['source_sha256']==docx['sha256']
        raw=self.bytes(dict(value,key='analysis',format='pdf'),self.output/language)
        assert raw.startswith(b'%PDF-')
        import pdfplumber
        with pdfplumber.open(io.BytesIO(raw)) as document:
            assert document.pages
            structural=dict(pages=len(document.pages),extracted_characters=[len(p.extract_text() or '') for p in document.pages],visual_review='pending')
        self.write_json(language+'/pdf.json',dict(value,structural_checks=structural))
        return value

    def report(self,language,finding,figure,*,title=None):
        title=title or 'CR-B05 '+self.label+(' 定量分析报告' if language=='zh-CN' else ' quantitative analysis report')
        body=dict(title=title,language=language,finding_version_id=finding['id'],figure_version_ids=[figure['id']])
        value=self.post('report-'+language,self.base+'/research-reports',body,'report');self.parent.wait(value['task_id'])
        value=self.get(self.base+'/research-reports/'+value['id']);folder=self.output/language
        raws,checked=self.verify_report(value,folder)
        self.write_json(language+'/table-verification.json',checked);self.write_json(language+'/report.json',value)
        docx=next(m for m in value['members'] if m['role']=='docx');pdf=self.pdf(language,docx)
        packaged=self.post('package-'+language,self.base+'/research-reports',dict(body,root_id=value['root_id'],expected_revision=value['revision'],include_pdf_id=pdf['id']),'report')
        self.parent.wait(packaged['task_id']);packaged=self.get(self.base+'/research-reports/'+packaged['id'])
        packaged_raws,packaged_checks=self.verify_report(packaged,folder/'with-pdf')
        with zipfile.ZipFile(io.BytesIO(packaged_raws['zip'])) as archive:assert shared.sha(archive.read('analysis.pdf'))==pdf['sha256']
        self.write_json(language+'/with-pdf/table-verification.json',packaged_checks)
        self.write_json(language+'/packaged-report.json',packaged)
        self.record.setdefault('deliveries',{}).setdefault(self.label,{})[language]=dict(project_id=self.project,finding_version_id=finding['id'],figure_version_id=figure['id'],report_version_id=value['id'],pdf_id=pdf['id'],packaged_report_version_id=packaged['id'],complete_tables=checked)
        self.parent.save();return packaged


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--path',required=True,choices=list(profiles()));parser.add_argument('--language',choices=['zh-CN','en'],default='zh-CN');parser.add_argument('--evidence',default='acceptance');args=parser.parse_args()
    acceptance=Acceptance(args.evidence);delivery=Delivery(acceptance,args.path)
    finding=delivery.finding();figure=delivery.figure();result=delivery.report(args.language,finding,figure)
    print(json.dumps(dict(path=args.path,language=args.language,report=result['id'],manuscript_publication=False),ensure_ascii=False))


if __name__=='__main__':main()
