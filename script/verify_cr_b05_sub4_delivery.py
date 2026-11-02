"""Use fixed fourth-batch sources in Chinese reports and complete PDF packages."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'script'), str(ROOT / 'script/dev'), str(ROOT / 'backend')]
from verify_cr_b05_sub4_acceptance import Acceptance
from verify_cr_b05_sub2_delivery import Delivery as PreviousDelivery
import cr_b04_downstream as shared
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE'] = '4'

NOTES = {
    'sequence-structure': '固定公开原件的有限序列与结构描述。RNA来源与T字母编码分别保留；蛋白前体与实验结构链分别保留身份，未进行比对或建立全长对应。Cα几何为选定model/author chain的蛋白有效坐标等权质心及回转半径。预声明ID筛选仅将RNA排除出蛋白/结构候选表，完整提取结果仍保留；不比较跨类型长度，不进行结构预测、疾病或因果推断。',
    'matched-omics': '作者预处理和预筛的两组学训练层，沿原始匹配标签作描述性整合。供体独立性与精确上游变换未核实，P值和BH为NA，不属于独立队列验证。STAT5A与STAT5-alpha只按冻结标签对应；HER2蛋白单独关联ERBB2外部证据，ERBB2 mRNA在原预筛层缺失。外部论文和正常组织图谱为原文陈述；同论文重复证据按来源组记录，未执行真实KO或独立公共验证。',
}


class Delivery(PreviousDelivery):
    def fixed_sources(self):
        labels = self.record.get('report_sources', {}).get(self.label)
        if labels is None:
            if self.label != 'sequence-structure':
                raise ValueError('Integration and evidence report sources must be explicitly frozen first')
            labels = ['sequence-structure-features']
        result = []
        for label in labels:
            entry = self.record['results'][label]
            if entry['project_id'] != self.project:
                raise ValueError('Report source is outside its project')
            value = self.get(self.base + '/bio-insight-results/' + entry['id'])
            if value['manifest_sha256'] != entry['manifest_sha256']:
                raise ValueError('Frozen report source SHA differs')
            source = dict(source_kind='bio_insight_result_version', source_id=value['id'],
                sha256=value['manifest_sha256'], locator=dict(kind='object'))
            result.append((source, value))
        return result

    def freeze_tables(self, fixed):
        for member in fixed['members']:
            if member['format'] not in ('tsv', 'csv'):
                continue
            identity = ('bio_insight_result_member', member['id'], member['key'])
            if identity in self.source_tables:
                continue
            raw = self.bytes(dict(member, key=member['id']), self.output / 'source-tables')
            columns, rows = shared.literal_rows(raw, member['format'])
            self.source_tables[identity] = dict(sha256=member['sha256'], columns=columns, rows=rows)
            self.source_raws[identity] = raw

    def finding(self):
        sources = []
        for source, fixed in self.fixed_sources():
            sources.append(source)
            self.freeze_tables(fixed)
            if self.label == 'sequence-structure':
                member = next(item for item in fixed['members'] if item['key'] == 'feature_results')
                raw = self.source_raws[('bio_insight_result_member', member['id'], member['key'])]
                rows = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), delimiter='\t'))
                fields = {'rna': ['length', 'gc_fraction', 'nucleotide_encoding'],
                    'protein': ['length', 'standard_count', 'stop_count'],
                    'structure': ['observed_residue_count', 'ca_count', 'centroid_x', 'centroid_y', 'centroid_z', 'radius_of_gyration']}
                for row in rows:
                    for column in fields[row['feature_kind']]:
                        sources.append(dict(source_kind='bio_insight_result_member', source_id=member['id'],
                            sha256=member['sha256'], locator=dict(kind='row', table='feature_results',
                                row_key=dict(row_key=row['row_key']), column=column)))
        self.write_json('source-table-universe.json', [dict(identity=list(key), sha256=value['sha256'],
            columns=value['columns'], rows=len(value['rows'])) for key, value in sorted(self.source_tables.items())])
        preview = self.preview_sources(sources)
        facts = [fact for catalog in preview['catalogs'] for fact in catalog['facts']]
        selected = list(dict.fromkeys(fact['id'] for fact in facts))
        if not selected or len(selected) > 1000:
            raise ValueError('Review the explicit fixed fact selection')
        supporting = [fact['id'] for fact in facts if fact['raw_value'] is not None
            and fact['verification_status'] not in ('missing', 'conflict')]
        claim = dict(id='scope', statement=NOTES[self.label], fact_ids=list(dict.fromkeys(supporting))[:100],
            origin='public_reanalysis', strength='exploratory', review_decision='adopt', limitations=[NOTES[self.label]])
        body = dict(title='序列与结构特征' if self.label == 'sequence-structure' else '多组学整合与外部证据',
            sources=sources, selected_fact_ids=selected, claims=[claim], notes=NOTES[self.label])
        value = self.post('finding', self.base + '/research-findings', body, 'finding')
        expected = {fact['id']: fact for fact in facts}
        if any(fact != expected[fact['id']] for fact in value['content']['facts']):
            raise ValueError('Published finding differs from fixed source facts')
        self.write_json('finding.json', value)
        return value

    def figure(self):
        keys = ['sequence-structure-figure'] if self.label == 'sequence-structure' else self.record['report_figures'][self.label]
        panels = []
        for index, key in enumerate(keys):
            entry = self.record['results'][key]
            value = self.get(self.base + '/bio-insight-results/' + entry['id'])
            if value['manifest_sha256'] != entry['manifest_sha256']:
                raise ValueError('Frozen figure SHA differs')
            member = next(item for item in value['members'] if item['format'] == 'png' and item['role'] != 'input_snapshot')
            panels.append(dict(source=dict(source_kind='bio_insight_result_member', source_id=member['id'],
                sha256=member['sha256'], locator=dict(kind='image')), label=chr(ord('A') + index)))
        mode = 'composite' if len(panels) > 1 else 'reuse'
        body = dict(mode=mode, panels=panels, title='序列与结构特征' if self.label == 'sequence-structure' else '整合与证据关系',
            caption=NOTES[self.label], language='zh-CN', figure_language='original', formats=['png', 'tiff', 'svg', 'pdf'],
            columns=2 if len(panels) > 3 else 1)
        value = self.post('figure-composite' if mode == 'composite' else 'figure', self.base + '/research-figures', body, 'figure')
        self.parent.wait(value['task_id'])
        value = self.get(self.base + '/research-figures/' + value['id'])
        for member in value['members']:
            self.bytes(member, self.output / 'figure')
        self.write_json('figure.json', value)
        return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label', choices=NOTES)
    args = parser.parse_args()
    acceptance = Acceptance()
    try:
        delivery = Delivery(acceptance, args.label)
        finding = delivery.finding()
        figure = delivery.figure()
        title = '序列与结构特征提取及筛选报告' if args.label == 'sequence-structure' else '多组学描述性整合与外部证据报告'
        report = delivery.report('zh-CN', finding, figure, title=title)
        print(json.dumps(dict(report_version_id=report['id'], visual=delivery.visual_preview()), ensure_ascii=False))
    finally:
        acceptance.client.close()
