"""Scoped B05/2 delivery. Default prepares only; --execute needs ready formal results.

No service control, uploads, model calls, historical packages or English report chain.
"""
import argparse
from copy import deepcopy
import csv
import io
import json
import os
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE'] = '2'
sys.path[:0] = [str(ROOT/'script'), str(ROOT/'script/dev'), str(ROOT/'backend')]
import cr_b04_downstream as shared
from verify_cr_b05_delivery import Delivery as PreviousDelivery


def table_identity(entry):
    source = entry['source']
    return source['source_kind'], source['source_id'], entry['key']


def exact_tables(entries, expected):
    identities = [table_identity(e) for e in entries]
    assert expected and len(identities) == len(set(identities)) and set(identities) == set(expected), 'Complete table universe differs'
    for entry in entries:
        original = expected[table_identity(entry)]
        assert entry['sha256'] == original['sha256'], 'Frozen table SHA differs'
        if 'rows' in entry:
            assert entry['rows'] == len(original['rows']), 'Complete table count differs'
        if 'expected_rows' in entry:
            assert entry['expected_rows'] == len(original['rows']), 'Declared full table count differs'


def ooxml_identity(raw):
    """Compare every content member, allowing only the two core time text fields."""
    parts = {}; times = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        infos = archive.infolist()
        assert len(infos) <= 512 and len({x.filename for x in infos}) == len(infos), 'OOXML members duplicated/oversized'
        assert sum(x.file_size for x in infos) <= shared.REPORT_ZIP_MAX_BYTES, 'OOXML expands beyond budget'
        for item in infos:
            content = archive.read(item)
            if item.filename == 'docProps/core.xml':
                core = ET.fromstring(content)
                for field in ('created', 'modified'):
                    nodes = core.findall('{http://purl.org/dc/terms/}'+field)
                    assert len(nodes) <= 1, 'Duplicate core time property'
                    if nodes:
                        assert not list(nodes[0]), 'Unexpected nested core time property'
                        times[field] = nodes[0].text
                        nodes[0].text = '__container_time__'
                content = ET.tostring(core, encoding='utf-8')
            parts[item.filename] = shared.sha(content)
    return dict(parts=parts, core_time_fields=times)


def verify_complete_workbook(raw, counts, expected, prior=None):
    exact_tables(counts['tables'], expected)
    universe = [dict(identity=list(k), sha256=v['sha256'], columns=v['columns'], rows=len(v['rows'])) for k,v in sorted(expected.items())]
    universe_sha = shared.digest(universe)
    current_sha = shared.sha(raw)
    identity = ooxml_identity(raw)
    if prior:
        assert prior['source_universe_sha256'] == universe_sha, 'Prior cell proof has another source universe'
        assert prior['counts'] == counts, 'Export counts changed since full cell check'
        if prior['xlsx_sha256'] == current_sha:
            mode = 'complete_xlsx_sha_reuse'
        else:
            assert prior['ooxml']['parts'] == identity['parts'], 'OOXML data/content changed; inspect before any broader verification'
            mode = 'identical_ooxml_member_sha_reuse'
        changes = {k:dict(before=prior['ooxml']['core_time_fields'].get(k), after=identity['core_time_fields'].get(k))
                   for k in ('created','modified') if prior['ooxml']['core_time_fields'].get(k) != identity['core_time_fields'].get(k)}
        return dict(prior, validation_mode=mode, current_xlsx_sha256=current_sha, allowed_core_time_changes=changes)
    # The accepted helper uses source_id as its key. Retag only this audit view,
    # so several complete analysis_run tables cannot overwrite one another.
    normalized = deepcopy(counts); original = {}
    for entry in normalized['tables']:
        key = table_identity(entry); token = json.dumps(key, ensure_ascii=False)
        original[token] = expected[key]
        entry['source'] = dict(entry['source'], source_id=token)
    checked = shared.verify_workbook(raw, normalized, original)
    return dict(validation_mode='all_source_table_cells_checked_once', xlsx_sha256=current_sha,
                source_universe_sha256=universe_sha, counts=counts, ooxml=identity, tables=checked)


def leaves(value, path=''):
    if isinstance(value, dict):
        for key,item in sorted(value.items()):
            yield from leaves(item, path+'.'+key if path else key)
    elif isinstance(value, list):
        for index,item in enumerate(value):
            yield from leaves(item, f'{path}[{index}]')
    else:
        yield path,value


def statistics_expected(source):
    """Independent section universe and literal rows from the frozen public source."""
    content = source['content']; result = content['result']; sections = {}
    for name in ('statistics','overall','groups','check','selection','row_audit'):
        if name in result: sections[name] = result[name]
    for name in ('role_records','frozen_role_audit','frozen_plot'):
        if name in content: sections[name] = content[name]
    sections['provenance'] = {name:result[name] for name in ('id','file_id','source_sha256','source','setup_revision','analysis_plan','analysis_context','engine','started_at','completed_at') if name in result}
    selection = result['selection']; declared_unit = selection.get('unit', selection.get('outcome_unit',''))
    def unit(path):
        if path in ('statistics.confidence_interval.low','statistics.confidence_interval.high') and selection.get('task_type') == 'group_comparison' and result.get('statistics',{}).get('estimate',{}).get('unit') == 'outcome': return declared_unit
        if path.endswith(('.n','_n')) or any(x in path.split('.') for x in ('p_value','statistic','coefficient','auc','survival','sample_sizes','df_numerator','df_denominator','matrix')): return ''
        if path == 'statistics.estimate.value' and result.get('statistics',{}).get('estimate',{}).get('unit') == 'outcome': return declared_unit
        if path.startswith(('overall.','groups.','groups[')) and path.rsplit('.',1)[-1] in ('mean','std','min','q1','median','q3','max','iqr'): return declared_unit
        return ''
    expected = {}; raws = {}
    prefix = 'statistics_'+shared.sha(source['source_id'].encode())[:12]+'_'
    for name,section in sections.items():
        columns = ['field_path','raw_type','raw_value','unit']; values = []
        for path,value in leaves(section):
            kind = 'null' if value is None else 'boolean' if type(value) is bool else 'integer' if type(value) is int else 'number' if type(value) is float else 'string'
            literal = value if kind == 'string' else json.dumps(value, ensure_ascii=False)
            values.append([path,kind,literal,unit(name+'.'+path)])
        stream = io.StringIO(newline=''); writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(columns); writer.writerows(values); raw = stream.getvalue().encode('utf-8')
        key = ('analysis_run', source['source_id'], prefix+name)
        expected[key] = dict(sha256=shared.sha(raw), columns=columns, rows=values)
        raws[prefix+name] = raw
    assert 'selection' in sections and 'check' in sections and 'role_records' in sections, 'New typed source must retain selection/check/role records'
    return expected, raws


NOTES = {
    'qpcr': 'PINK1 / UBC，4次独立induction的同板配对ΔCq检验；4 induction不是4名供体。沿用作者等效率假设，未测定assay效率；给定效率模式仅有独立合成算术验证。原作者相对量的校准配置不完整，与系统配对配置不同；原值、重算值、差异和容差保留于完整核对表，不宣称复现原检验。技术孔不增加生物学n。',
    'phenotype': 'sacurine元数据的一个预设探索性BMI M-F Welch比较，单位未知，未调整age；统计来自已保存正式analysis_run，进入报告不会重新拟合。研究设计假设不能由工程检查证明，不代表独立临床或生物学验证。',
}


def scope_claim(label, facts):
    """Cite actual comparison values; missing/conflicting facts stay selected only."""
    supporting = []
    for fact in facts:
        value = fact['raw_value']; locator = fact['locator']
        if fact['verification_status'] in ('missing','conflict') or value is None or value in ('','NA'):
            continue
        if label == 'qpcr':
            relevant = locator.get('table') == 'comparison_results' and locator.get('column') in (
                'effect_value','p_value','q_within_contrast','n_numerator','n_denominator','n_pairs',
                'fold_change','ci_fold_low','ci_fold_high')
        else:
            path = locator.get('field_path','')
            relevant = type(value) in (int,float) and (
                path == 'check.valid_count' or path.startswith(('statistics.','groups[')))
        if relevant and fact['id'] not in supporting:
            supporting.append(fact['id'])
    assert supporting, 'No actual nonmissing comparison facts support the scope claim'
    return dict(id='scope-'+label,statement=NOTES[label],fact_ids=supporting[:100],
        origin='public_reanalysis',strength='exploratory',review_decision='adopt',
        limitations=['工程交付验证不等于生物学验证或用户验收；完整结果以固定来源为准。'])


def failed_revision_request(original, body):
    assert original['task']['status'] == 'failed', 'Explicit repair requires a known failed version'
    assert original['root_id'] and original['revision'] >= 1
    return dict(body, root_id=original['root_id'], expected_revision=original['revision'])


class Delivery(PreviousDelivery):
    def __init__(self, acceptance, label, *, repair_failed_report=False, repair_failed_figure=False):
        super().__init__(acceptance,label)
        self.source_raws = {}; self.preview = None
        self.repair_failed_report = repair_failed_report
        self.repair_failed_figure = repair_failed_figure

    def post(self, label, path, body, kind=None, recover=None):
        repairing = (label == 'report-zh-CN' and self.repair_failed_report) or (label == 'figure' and self.repair_failed_figure)
        if repairing:
            entry = self.record['actions'].get(self.label+'-delivery-'+label)
            assert entry and entry.get('response'), 'Repair needs the retained known original response; unknown submissions must be recovered first'
            assert entry['body'] == body, 'Repair may not change the fixed source request'
            original = self.get(path+'/'+entry['response']['id'])
            repaired = failed_revision_request(original,body)
            repair_label = label+'-repair-'+str(original['revision'])
            self.write_json('recovery-'+label+'.json',dict(original_version_id=original['id'],original_task=original['task'],
                method='explicit_same_root_revision',new_action_label=self.label+'-delivery-'+repair_label,
                request=repaired,history='original failed task and request retained; no retry-rule widening or blind re-POST'))
            return super().post(repair_label,path,repaired,kind,recover)
        return super().post(label,path,body,kind,recover)

    def preview_sources(self, sources):
        value = self.check(self.client.post(self.base+'/research-results/preview', json=dict(sources=sources))).json()
        self.write_json('source-preview.json', value); self.preview = value
        return value

    def formal_source(self):
        key = 'qpcr-comparison' if self.label == 'qpcr' else 'phenotype-statistics'
        record = self.record['results'][key]
        if self.label == 'qpcr':
            value = self.get(self.base+'/bio-insight-results/'+record['id'])
            assert value['manifest_sha256'] == record['manifest_sha256'], 'Frozen qPCR result differs'
            source = dict(source_kind='bio_insight_result_version', source_id=value['id'], sha256=value['manifest_sha256'], locator=dict(kind='object'))
            return source,value
        source = dict(source_kind='analysis_run',source_id=record['id'],locator=dict(kind='object'))
        value = self.preview_sources([source])
        fixed = value['catalogs'][0]['source']
        assert fixed['source_id'] == record['id'] and fixed['project_id'] == self.project
        assert fixed['content']['result']['id'] == record['id']
        return dict(source, sha256=fixed['sha256']), fixed

    def freeze_tables(self, fixed):
        if self.source_tables: return
        if self.label == 'qpcr':
            for member in fixed['members']:
                if member['format'] not in ('csv','tsv'): continue
                raw = self.bytes(dict(member,key=member['id']),self.output/'source-tables')
                columns,values = shared.literal_rows(raw,member['format'])
                key = ('bio_insight_result_member',member['id'],member['key'])
                assert key not in self.source_tables
                self.source_tables[key] = dict(sha256=member['sha256'],columns=columns,rows=values)
                self.source_raws[member['key']] = raw
        else:
            self.source_tables,self.source_raws = statistics_expected(fixed)
            for key,raw in self.source_raws.items():
                target = self.output/'source-tables'/(key+'.tsv'); target.parent.mkdir(exist_ok=True)
                if target.exists(): assert target.read_bytes() == raw, 'Frozen statistics literal rows differ'
                else: target.write_bytes(raw)
        self.write_json('source-table-universe.json', [dict(identity=list(k),sha256=v['sha256'],columns=v['columns'],rows=len(v['rows'])) for k,v in sorted(self.source_tables.items())])

    def finding(self):
        source,fixed = self.formal_source(); self.freeze_tables(fixed); sources = [source]
        representative = None; columns = []
        if self.label == 'qpcr':
            rows = list(csv.DictReader(io.StringIO(self.source_raws['comparison_results'].decode('utf-8-sig')),delimiter='\t'))
            representative = next(row for row in rows if row['p_value'] not in ('','NA'))
            member = next(m for m in fixed['members'] if m['key'] == 'comparison_results')
            columns = [key for key in ('effect_value','p_value','q_within_contrast','n_numerator','n_denominator','n_pairs','fold_change','ci_fold_low','ci_fold_high') if key in representative]
            sources += [dict(source_kind='bio_insight_result_member',source_id=member['id'],sha256=member['sha256'],locator=dict(kind='row',table='comparison_results',row_key=dict(row_key=representative['row_key']),column=column)) for column in columns]
            preview = self.preview_sources(sources)
        else:
            preview = self.preview
        facts = [fact for catalog in preview['catalogs'] for fact in catalog['facts']]
        selected = list(dict.fromkeys(fact['id'] for fact in facts))
        assert selected and len(selected) <= 1000, 'No frozen facts or fact budget exceeded'
        # Claims are scoped observations only, with the design limits carried into
        # both the readable report and frozen finding (notes alone are not rendered).
        claim = scope_claim(self.label,facts)
        body = dict(title='CR-B05 子包二 '+('qPCR同板配对探索' if self.label == 'qpcr' else '表型BMI预设探索比较'),sources=sources,selected_fact_ids=selected,claims=[claim],notes=NOTES[self.label])
        value = self.post('finding',self.base+'/research-findings',body,'finding')
        self.write_json('finding.json',value)
        actual = {fact['locator']['column']:fact['raw_value'] for fact in value['content']['facts'] if self.label == 'qpcr' and fact['source_id'] == member['id']}
        if self.label == 'qpcr': assert actual == {column:representative[column] for column in columns}, 'Finding differs from frozen qPCR row'
        else:
            expected = {fact['id']:fact for fact in facts}
            assert all(fact == expected[fact['id']] for fact in value['content']['facts']), 'Statistics finding altered saved facts'
        return value

    def figure(self):
        if self.label == 'qpcr':
            record = self.record['results']['qpcr-figure']
            result = self.get(self.base+'/bio-insight-results/'+record['id'])
            assert result['manifest_sha256'] == record['manifest_sha256']
            member = next(m for m in result['members'] if m['format'] == 'png' and m['role'] != 'input_snapshot')
            panel = dict(source=dict(source_kind='bio_insight_result_member',source_id=member['id'],sha256=member['sha256'],locator=dict(kind='image')),label='A')
        else:
            fixed = self.preview['catalogs'][0]['source']
            panel = dict(source=dict(source_kind='analysis_run',source_id=fixed['source_id'],sha256=fixed['sha256'],locator=dict(kind='object')),member_key='statistics',label='A')
        body = dict(mode='reuse',panels=[panel],title='CR-B05 子包二 '+self.label,caption=NOTES[self.label],language='zh-CN',figure_language='zh-CN' if self.label == 'phenotype' else 'original',formats=['png','tiff','svg','pdf'],columns=1)
        value = self.post('figure',self.base+'/research-figures',body,'figure'); self.parent.wait(value['task_id'])
        value = self.get(self.base+'/research-figures/'+value['id'])
        for member in value['members']: self.bytes(member,self.output/'figure')
        self.write_json('figure.json',value); return value

    def table_sources(self, report):
        assert self.source_tables, 'Freeze formal source table universe before reporting'
        exact_tables(report['content']['tables'],self.source_tables)
        exact_tables(report['manifest']['row_counts']['tables'],self.source_tables)

    def verify_report(self,value,folder):
        raws = self.report_members(value,folder); self.table_sources(value)
        proof_path = self.output/'complete-table-cell-proof.json'
        prior = json.loads(proof_path.read_text(encoding='utf-8')) if proof_path.exists() else None
        proof = verify_complete_workbook(raws['xlsx'],value['manifest']['row_counts'],self.source_tables,prior)
        if prior is None: self.write_json(proof_path.name,proof)
        finding = value['content']['finding']['content']
        with zipfile.ZipFile(io.BytesIO(raws['zip'])) as archive:
            assert archive.read('results.xlsx') == raws['xlsx'] and archive.read('analysis.docx') == raws['docx']
            for index,table in enumerate(value['content']['tables']):
                raw_key = table_identity(table) if table_identity(table) in self.source_raws else table['key']
                assert archive.read(f'tables/table_{index:03d}.tsv') == self.source_raws[raw_key], 'Complete package table differs from frozen source'
            parameters = json.loads(archive.read('parameters.json'))
            assert parameters == [method.get('parameters',{}) for method in finding['methods']], 'Complete Methods parameters lost'
            assert json.loads(archive.read('sources.json')) == finding['sources'], 'Frozen source identities changed'
            if self.label == 'phenotype':
                fixed = next(source for source in finding['sources'] if source['source_kind'] == 'analysis_run')
                prefix = 'statistics/'+shared.sha(fixed['source_id'].encode())[:16]+'/'
                assert json.loads(archive.read(prefix+'frozen_source.json')) == fixed, 'Statistics projection package lost frozen source'
                assert json.loads(archive.read(prefix+'result.json')) == fixed['content']['result'], 'Statistics projection package altered saved result'
                assert {prefix+name for name in ('frozen_source.json','result.json','rebuild_projection.py','README.txt')} <= set(archive.namelist()), 'Frozen projection reproduction members missing'
        methods = raws['methods'].decode('utf-8')
        for method in finding['methods']:
            literal = json.dumps({key:method.get(key,{}) for key in ('executed','parameters','software','source')},ensure_ascii=False,sort_keys=True)
            assert literal in methods, 'Methods text lost frozen parameters/software/source'
        with zipfile.ZipFile(io.BytesIO(raws['docx'])) as archive:
            root = ET.fromstring(archive.read('word/document.xml'))
            text = ''.join(root.itertext())
            assert value['content']['title'] in text and finding['claims'][0]['statement'] in text, 'DOCX omitted report scope/limits'
        assert value['content']['real_model_calls'] == 0
        return raws,proof

    def pdf(self,language,docx):
        # Retains existing exact request-key recovery and pinned DOCX/PDF SHA checks.
        return super().pdf(language,docx)

    def visual_preview(self):
        """Render retained PDF pages as a single contact sheet; manual review stays pending."""
        import pdfplumber
        from PIL import Image,ImageOps,ImageDraw
        folder = self.output/'zh-CN'; path = folder/'analysis.pdf'
        pages = []
        with pdfplumber.open(path) as document:
            for index,page in enumerate(document.pages):
                picture = page.to_image(resolution=60).original.convert('RGB')
                picture = ImageOps.expand(picture,border=(2,22,2,2),fill='white')
                ImageDraw.Draw(picture).text((8,4),f'Page {index+1}',fill='black'); pages.append(picture)
        width = max(p.width for p in pages); height = max(p.height for p in pages)
        columns = min(3,len(pages)); rows = (len(pages)+columns-1)//columns
        sheet = Image.new('RGB',(columns*width,rows*height),'#cccccc')
        for index,picture in enumerate(pages): sheet.paste(picture,((index%columns)*width,(index//columns)*height))
        target = folder/'pdf-contact-sheet.png'
        if not target.exists(): sheet.save(target)
        return dict(pdf=str(path),contact_sheet=str(target),pages=len(pages),visual_review='pending_actual_view')


def acquire_reproductions(acceptance):
    """Acquire/verify exactly the two new qPCR packages, serially, once each."""
    from verify_cr_b05_reproduction import acquire
    evidence = {}
    for kind in ('comparison','figure'):
        root = acceptance.output/'reproduction'/('qpcr-'+kind)
        if (root/'verification.json').exists():
            receipt = json.loads((root/'acquisition.json').read_text(encoding='utf-8'))
            record = acceptance.record['results']['qpcr-'+kind]
            assert receipt['result_id'] == record['id'] and shared.sha((root/'formal-package.zip').read_bytes()) == receipt['archive_sha256']
            verification = json.loads((root/'verification.json').read_text(encoding='utf-8'))
            assert verification['status'] == 'verified'
            package = root/'package'
        else:
            root,package,receipt = acquire(acceptance,'qpcr',kind)
        operation = 'recompute' if kind == 'comparison' else 'render'
        output = root/('root-'+operation+'-attempt')
        image = acceptance.state['worker_image_id']
        command = ['docker','run','--name','pa-b05-sub2-'+operation+'-'+receipt['archive_sha256'][:12],
            '--network','none','--read-only','--memory','4g','--cpus','1','--pids-limit','64','--tmpfs','/tmp:rw,size=1g',
            '--mount','type=bind,source='+str(package.resolve())+',target=/package,readonly',
            '--mount','type=bind,source='+str(output.resolve())+',target=/attempt',
            '--entrypoint','/opt/paperassist-bio-insights/bin/python',image,'-B','/package/reproduce.py',operation,
            '--output','/attempt/output','--manifest-sha256',receipt['manifest_sha256']]
        evidence[kind] = dict(package=str(package),manifest_sha256=receipt['manifest_sha256'],verification=str(root/'verification.json'),
            operation=operation,actual_execution='pending_root',root_create_new_attempt_directory=str(output),command=command,timeout_seconds=2100,
            instructions='Root must check image identity/budget and absent prior attempt/container before running once; retain stdout/stderr/exit code and operation.json. No --rm; no independent repeat acquire/verify. Offline operation retains its required internal byte checks.')
    target = acceptance.output/'reproduction'/'new-package-handoff.json'
    if not target.exists(): target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path',choices=['qpcr','phenotype'])
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--reproduction-packages',action='store_true')
    parser.add_argument('--visual-preview',action='store_true')
    parser.add_argument('--repair-failed-report',action='store_true',help='Explicit same-root revision of retained failed Chinese report; preserves finding/figure')
    parser.add_argument('--repair-failed-figure',action='store_true',help='Explicit same-root revision of retained failed research figure; preserves source/config')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(dict(status='prepared_not_executed',paths=['qpcr','phenotype'],language='zh-CN',historical_validation='not_repeated',full_table_check='once_then_exact_member_SHA_reuse',reproduction='two_new_qpcr_packages_verify_once; root executes one recompute and one render',service_control=False),ensure_ascii=False)); return
    if not args.path and not args.reproduction_packages: parser.error('--execute requires --path or --reproduction-packages')
    from verify_cr_b05_sub2_acceptance import Acceptance
    acceptance = Acceptance()
    try:
        if args.reproduction_packages:
            print(json.dumps(acquire_reproductions(acceptance),ensure_ascii=False)); return
        delivery = Delivery(acceptance,args.path,repair_failed_report=args.repair_failed_report,repair_failed_figure=args.repair_failed_figure)
        finding = delivery.finding(); figure = delivery.figure(); report = delivery.report('zh-CN',finding,figure)
        result = dict(path=args.path,report=report['id'],evidence=str(delivery.output),user_acceptance='pending',biological_validation='not_performed')
        if args.visual_preview: result['visual'] = delivery.visual_preview()
        print(json.dumps(result,ensure_ascii=False))
    finally:
        acceptance.client.close()


if __name__ == '__main__': main()
