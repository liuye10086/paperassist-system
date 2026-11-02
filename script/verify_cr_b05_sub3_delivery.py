"""Reuse frozen sub3 results in complete Chinese reports; no model calls."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'script'),str(ROOT/'script/dev'),str(ROOT/'backend')]
from verify_cr_b05_sub3_acceptance import Acceptance
from verify_cr_b05_sub2_delivery import Delivery as PreviousDelivery
import cr_b04_downstream as shared
os.environ['PAPERASSIST_CR_B05_SUBPACKAGE']='3'

NOTES={
 'pbmc3k':'PBMC3k公开单供体2700细胞输入的探索性重分析。细胞数量不等于独立供体数；QC、聚类、marker和标签不证明细胞类型或因果机制，不执行真实供体差异推断。HVG、PCA、UMAP、Leiden及过滤参数均保留于Methods，完整细胞、基因、marker与标签依据表保留。',
 'enterotype':'phyloseq固定版本enterotype完整553属级特征与280样本的描述性重分析。来源为相对丰度，按明确计划逐样本闭合并保留原总和与系数；非零属数不代表原始测序深度或绝对菌量。时间重复、队列及测序技术混杂限制独立可交换性，本真实材料不作无限制PERMANOVA/PERMDISP推断，工程数值验证另列。'
}

class Delivery(PreviousDelivery):
    def formal_source(self):
        if self.label=='pbmc3k':
            item=self.record['paths'][self.label];value=self.get(self.base+'/bio-processed-datasets/'+item['processed_id'])
            assert value['manifest_sha256']==item['processed_source']['manifest_sha256']
            return dict(source_kind='bio_processed_dataset_version',source_id=value['id'],sha256=value['manifest_sha256'],locator=dict(kind='object')),value
        item=self.record['results'][self.label+'-comparison'];value=self.get(self.base+'/bio-insight-results/'+item['id'])
        assert value['manifest_sha256']==item['manifest_sha256']
        return dict(source_kind='bio_insight_result_version',source_id=value['id'],sha256=value['manifest_sha256'],locator=dict(kind='object')),value

    def freeze_tables(self,fixed):
        if self.source_tables:return
        selected={t['key'] for t in fixed['manifest']['tables']} if self.label=='pbmc3k' else None
        for member in fixed['members']:
            if member['format'] not in ('csv','tsv') or selected is not None and member['key'] not in selected:continue
            raw=self.bytes(dict(member,key=member['id']),self.output/'source-tables')
            columns,values=shared.literal_rows(raw,member['format'])
            kind='bio_analysis_artifact' if self.label=='pbmc3k' else 'bio_insight_result_member'
            key=(kind,member['id'],member['key']);assert key not in self.source_tables
            self.source_tables[key]=dict(sha256=member['sha256'],columns=columns,rows=values)
            self.source_raws[member['key']]=raw
        self.write_json('source-table-universe.json',[dict(identity=list(k),sha256=v['sha256'],columns=v['columns'],rows=len(v['rows'])) for k,v in sorted(self.source_tables.items())])

    def finding(self):
        source,fixed=self.formal_source();self.freeze_tables(fixed)
        preview=self.preview_sources([source]);facts=[f for c in preview['catalogs'] for f in c['facts']]
        selected=list(dict.fromkeys(f['id'] for f in facts));assert selected and len(selected)<=1000
        claim=dict(id='scope',statement=NOTES[self.label],fact_ids=selected,origin='public_reanalysis',strength='exploratory',review_decision='adopt',limitations=[NOTES[self.label]])
        body=dict(title='CR-B05 子包三 '+('单细胞探索' if self.label=='pbmc3k' else '微生物群落描述'),sources=[source],selected_fact_ids=selected,claims=[claim],notes=NOTES[self.label])
        value=self.post('finding',self.base+'/research-findings',body,'finding');self.write_json('finding.json',value)
        expected={f['id']:f for f in facts}
        assert all(f==expected[f['id']] for f in value['content']['facts'])
        return value

    def figure(self):
        if self.label=='pbmc3k':
            _,fixed=self.formal_source()
            repaired=self.record['paths'][self.label].get('repaired_figure_id')
            value=self.get(self.base+'/bio-figures/'+repaired) if repaired else next(f for f in fixed['figures'] if f['config']['kind']=='umap')
            member=next(m for m in value['members'] if m['format']=='png')
            source=dict(source_kind='bio_figure_version',source_id=value['id'],sha256=value['manifest_sha256'],locator=dict(kind='image'))
            panel=dict(source=source,member_key=member['key'],label='A')
        else:
            entry=self.record['results'][self.label+'-figure'];value=self.get(self.base+'/bio-insight-results/'+entry['id'])
            member=next(m for m in value['members'] if m['format']=='png' and m['role']!='input_snapshot')
            panel=dict(source=dict(source_kind='bio_insight_result_member',source_id=member['id'],sha256=member['sha256'],locator=dict(kind='image')),label='A')
        body=dict(mode='reuse',panels=[panel],title='CR-B05 子包三 '+self.label,caption=NOTES[self.label],language='zh-CN',figure_language='original',formats=['png','tiff','svg','pdf'],columns=1)
        result=self.post('figure',self.base+'/research-figures',body,'figure');self.parent.wait(result['task_id']);result=self.get(self.base+'/research-figures/'+result['id'])
        for item in result['members']:self.bytes(item,self.output/'figure')
        self.write_json('figure.json',result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('label',choices=list(NOTES));parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    if not args.execute:print(json.dumps(dict(scope=NOTES[args.label],executed=False),ensure_ascii=False));return
    acceptance=Acceptance()
    try:
        delivery=Delivery(acceptance,args.label);finding=delivery.finding();figure=delivery.figure();report=delivery.report('zh-CN',finding,figure)
        print(json.dumps(dict(report_version_id=report['id'],visual=delivery.visual_preview()),ensure_ascii=False))
    finally:acceptance.client.close()

if __name__=='__main__':main()
