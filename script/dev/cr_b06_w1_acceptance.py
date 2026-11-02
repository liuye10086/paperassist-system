"""W1 fixed-source A19 acceptance and offline qPCR handoff.

Default only prints the frozen plan. --execute creates recoverable candidates;
--execute --publish explicitly adopts reviewed engineering candidates as new
roots and exports DOCX/PDF. Never starts services or rebuilds source reports.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'script/dev'), str(ROOT / 'backend')]
from cr_b04_downstream import Acceptance, digest, sha
from app.domain.research_results.fact_draft import compose
from app.domain.manuscripts.research_sources import project_source
from app.adapters.research_method_text import METHOD_PRESENTATION_VERSION

RUNTIME = ROOT / 'script/.runtime/client-requirements-b06-w1'
B04 = ROOT / 'script/.runtime/client-requirements-b04/downstream/gse-b04-actual'
QPCR = ROOT / 'script/.runtime/client-requirements-b05-sub2/acceptance/reports/qpcr'
PROJECT = 'e8ba52c6-0e85-42ac-8205-dd70f1851f03'
FINDING = 'c4f0c285-cf2b-5853-ba56-d8b67c82d602'
FIGURE = '1cd77847-e6f7-5494-90a1-620f2d0826d7'
REPORTS = {'en': '87dccff2-0d06-5d51-a6cf-af343b07c7b8',
           'zh-CN': '0f0e0a01-90db-51c2-b2d0-378d2f31bab0'}
QPCR_PROJECT = 'd8d0d415-0652-4d1b-9595-2bbf5924c094'
QPCR_FINDING = '1300d5ce-d515-523a-8e3b-f1cfa42a3b6d'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def retain(path, value):
    """Evidence is append-only by identity; never overwrite different bytes."""
    path = Path(path)
    if path.exists():
        if read(path) != value:
            raise ValueError('Retained evidence differs: ' + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def qpcr_payload():
    path = QPCR / 'finding.json'
    finding = read(path)
    if finding['id'] != QPCR_FINDING or digest(finding['content']) != finding['sha256']:
        raise ValueError('Fixed qPCR finding identity/content differs')
    files = sorted({identity for source in finding['content']['sources']
                    for identity in source.get('source_file_ids', [])})
    source = project_source(dict(source_kind='research_finding_version', source_id=finding['id'],
        title='CR-B05 qPCR saved finding', sha256=finding['sha256'], locator={'kind': 'object'},
        source_file_ids=files, content=finding['content']))
    payload = dict(schema_version=1, method_presentation_version=METHOD_PRESENTATION_VERSION,
        project_id=QPCR_PROJECT, document_context={'delivery_id': 'offline-context-only', 'document_kind': 'sci'},
        sources=[source], selected_source_ids=[source['id']], base_snapshot=None, base_version_id=None,
        expected_revision=0, output_language='zh-CN', thesis_context=None, thesis=None,
        sections=['results', 'materials_and_methods'], manual_notes='Local saved-source handoff only; no API candidate or publication.')
    return payload, dict(path=str(path), file_sha256=sha(path.read_bytes()), finding_id=finding['id'],
        finding_sha256=finding['sha256'], project_id=QPCR_PROJECT,
        source_authorization='offline snapshot only; no API source authorization claimed')


def check_qpcr(payload, candidate):
    content = payload['sources'][0]['content']
    facts = [p['research_fact'] for g in candidate['results_groups'] for p in g['paragraphs']]
    methods = [p['research_method'] for p in candidate['methods']]
    expected = [f for f in content['facts'] if f['verification_status'] not in ('missing', 'conflict')]
    if facts != expected or methods != content['methods']:
        raise ValueError('qPCR exact facts or Methods changed in local handoff')
    visible = '\n'.join([p['text'] for p in candidate['methods']] +
        [p['text'] for g in candidate['results_groups'] for p in g['paragraphs']] +
        candidate['research_warnings'] + candidate['research_gaps'] +
        [c['statement'] for c in candidate['research_claims']])
    limits = dict(technical_not_biological_n=('technical wells do not increase biological n' in visible or '技术孔不增加生物学n' in visible),
        induction_not_donors=('4' in visible and 'induction' in visible and ('供体' in visible or 'donor' in visible)),
        efficiency_assumption=('等效率假设' in visible),
        efficiency_not_measured=('无测定效率' in visible or '未测定assay效率' in visible),
        original_calibration_gap=('校准配置' in visible),
        arithmetic_only_efficiency_mode=('合成算术验证' in visible))
    if not all(limits.values()) or candidate['real_model_calls'] is not False or candidate['real_network_calls'] is not False:
        raise ValueError('qPCR limitations or zero-call boundary missing: ' + json.dumps(limits))
    return dict(exact_facts_preserved=True, exact_methods_preserved=True,
        fact_count=len(facts), method_count=len(methods), limits=limits,
        numeric_binding_count=sum(len(p['numeric_bindings']) for g in candidate['results_groups'] for p in g['paragraphs']))


def qpcr_handoff(output):
    payload, source = qpcr_payload()
    candidate = compose(payload)
    checks = check_qpcr(payload, candidate)
    proof = dict(status='local_saved_source_context_verified', source=source, checks=checks,
        candidate_sha256=digest(candidate), real_model_calls=0, real_network_calls=0,
        scientific_recompute=False, api_candidate_created=False, published=False,
        limitations=['Local actual project_source/compose only; API permissions and task chain not exercised',
                     'Partial Results/Methods context; no complete manuscript or biological validation'])
    retain(output / 'payload.json', payload)
    retain(output / 'candidate.json', candidate)
    retain(output / 'receipt.json', proof)
    return proof


def check_projection(payload,candidate):
    """Independently derive full-record uniqueness and every carrier source."""
    if payload.get('fact_projection_version')!=2 or candidate.get('research_bridge',{}).get('fact_projection_version')!=2:
        raise ValueError('W1 adoption requires explicit fact projection v2')
    facts={};methods={}
    for source in payload['sources']:
        if source['id'] not in payload['selected_source_ids']:continue
        content=source['content']
        blocked={fid for conflict in content.get('conflicts',[]) if conflict['decision']=='unresolved' for fid in conflict['fact_ids']}
        for record,key,target in [(f,'research_fact',facts) for f in content.get('facts',[])
                if f['id'] not in blocked and f['verification_status'] not in ('missing','conflict')]+[(m,'research_method',methods) for m in content.get('methods',[])]:
            identity=digest(record)
            if identity not in target:target[identity]=dict(record=record,source_ids=[])
            if source['id'] not in target[identity]['source_ids']:target[identity]['source_ids'].append(source['id'])
    fact_paragraphs=[p for group in candidate['results_groups'] for p in group['paragraphs'] if 'research_fact' in p]
    method_paragraphs=[p for p in candidate['methods'] if 'research_method' in p]
    for paragraphs,expected,key in [(fact_paragraphs,facts,'research_fact'),(method_paragraphs,methods,'research_method')]:
        if len(paragraphs)!=len(expected):raise ValueError('Projected full records are missing or duplicated: '+key)
        for paragraph,entry in zip(paragraphs,expected.values()):
            if paragraph[key]!=entry['record'] or paragraph['source_ids']!=entry['source_ids']:
                raise ValueError('Projected full record or complete carrier source_ids differs: '+key)
    if candidate['sources']!=payload['sources']:raise ValueError('Candidate lost its complete frozen sources')
    return dict(fact_projection_version=2,unique_fact_count=len(facts),unique_method_count=len(methods),
        exact_full_records_preserved=True,all_carrier_source_ids_preserved=True)


def reuse_snapshots(evidence,schema):
    """Opt-in reuse of this W1 clone's successful full-read evidence, locally."""
    evidence=Path(evidence).resolve()
    if not evidence.is_relative_to(RUNTIME.resolve()) or evidence==RUNTIME.resolve():
        raise ValueError('Reuse evidence must belong to a dedicated W1 run')
    receipt_path=evidence/'receipt.json';inventory_path=evidence/'fixed-source-inventory.json'
    receipt=read(receipt_path);inventory=read(inventory_path)
    if receipt['identity']['schema']!=schema or receipt['identity']['project_id']!=PROJECT:
        raise ValueError('Source reuse evidence belongs to another clone or project')
    finding=read(B04/'finding.json');reports={language:read(B04/language/'report.json') for language in REPORTS}
    expected_figures={f['id']:f for report in reports.values() for f in report['content']['figures']}
    figure=expected_figures[FIGURE]
    expected=dict(finding=dict(id=FINDING,sha256=finding['sha256']),
        figure=dict(id=FIGURE,sha256=figure['manifest_sha256']),
        reports={language:dict(id=report['id'],sha256=report['sha256']) for language,report in reports.items()})
    if inventory!=expected or finding['id']!=FINDING or digest(finding['content'])!=finding['sha256']:
        raise ValueError('Retained full-read inventory or local finding differs')
    for language,report in reports.items():
        if report['id']!=REPORTS[language] or digest(report['content'])!=report['sha256'] or report['content']['finding']['id']!=FINDING:
            raise ValueError('Retained local report binding differs')
    paths=[receipt_path,inventory_path,B04/'finding.json',*(B04/language/'report.json' for language in REPORTS)]
    proof=dict(mode='explicit_W1_full_read_evidence_reuse',schema=schema,project_id=PROJECT,
        prior_full_read_inventory=str(inventory_path),local_snapshot_files=[dict(path=str(path),sha256=sha(path.read_bytes())) for path in paths],
        new_asset_byte_verification=False,product_source_validation='unchanged; candidate API validates full sources independently',
        limitation='This wrapper rechecks current owner/project source records and local snapshot bytes; it does not claim new full asset-byte verification')
    return (finding,figure,reports),proof


def check_source_records(local,records,owner):
    finding,figure,reports=local
    expected=[('finding',finding,records['finding']),('figure',figure,records['figure'])]
    expected.extend(('report-'+language,report,records['reports'][language]) for language,report in reports.items())
    signatures={}
    for kind,snapshot,row in expected:
        if row is None or row['id']!=snapshot['id'] or row['project_id']!=PROJECT or row['user_id']!=owner:
            raise ValueError('Fixed source record is absent or outside the owner/project: '+kind)
        if kind=='figure':
            if (row['config_json']!=snapshot['config'] or digest(row['config_json'])!=row['config_sha256']
                    or row['manifest_sha256']!=snapshot['manifest_sha256'] or row['manifest_object_id'] is None):
                raise ValueError('Fixed figure record differs')
        elif row['content_json']!=snapshot['content'] or row['content_sha256']!=snapshot['sha256'] or digest(row['content_json'])!=row['content_sha256']:
            raise ValueError('Fixed source content differs: '+kind)
        if kind=='finding':
            if row['set_id']!=snapshot['set_id']:raise ValueError('Fixed finding set differs')
        else:
            expected_type='research_figure' if kind=='figure' else 'research_report'
            if row['resolved_task_status']!='succeeded' or row['resolved_task_type']!=expected_type:
                raise ValueError('Fixed source task is incomplete or has another type: '+kind)
            if kind.startswith('report-') and (row['manifest_sha256']!=snapshot['manifest_sha256']
                    or row['manifest_object_id'] is None or row['finding_version_id']!=FINDING):
                raise ValueError('Fixed report manifest/finding binding differs')
        signatures[kind]=digest(row)
    return signatures


def review_candidate(preview, value, body):
    """Bind exact real compose output, sources and new-root target before adoption."""
    if (body.get('manuscript_id') is not None or body.get('base_version_id') is not None
            or body.get('expected_revision') != 0 or value.get('manuscript_id') is not None
            or value.get('expected_revision') != 0):
        raise ValueError('W1 candidate must target a new root')
    selected = set(preview['selected_source_ids'])
    requested = set(body['finding_version_ids'] + body['figure_version_ids'] + body['report_version_ids'])
    if not requested <= selected or not selected <= {s['id'] for s in preview['sources']}:
        raise ValueError('Candidate fixed-source selection differs')
    actual = compose(preview)
    if (preview['writing_scope'] != 'results_methods' or actual.get('writing_scope') != 'results_methods'
            or preview['real_model_calls'] is not False or preview['real_network_calls'] is not False
            or actual['real_model_calls'] is not False or actual['real_network_calls'] is not False
            or actual != preview['merge_preview'] or actual != value['candidate']
            or digest(actual) != value['candidate_sha256']):
        raise ValueError('Candidate changed or differs from exact fixed-source compose preview')
    projection=check_projection(preview,value['candidate'])
    return dict(candidate_id=value['id'], candidate_sha256=value['candidate_sha256'],
        selected_source_ids=sorted(selected), fixed_sources_verified=True,
        exact_compose_matches=True, manuscript_id=None, expected_revision=0,
        decision='adopt_for_authorized_engineering_acceptance',
        scientific_signoff=False, word_visual_acceptance=False, real_model_calls=0,projection=projection)


class W1Acceptance(Acceptance):
    def candidate_review(self, kind):
        entry = self.record['actions']['candidate-' + kind]
        # Base writing() already waited for success, GET the exact candidate,
        # checked its new-root scope and saved these immutable result fields.
        # Reuse that successful API read; publication still validates product
        # sources independently rather than relying on this acceptance proof.
        path=self.output/kind/'candidate.json'
        saved=read(path);body=entry['body'];response=entry['response']
        if (saved['id']!=response['id'] or saved['delivery_id']!=body['delivery_id']
                or response['delivery_id']!=body['delivery_id']
                or body['manuscript_id'] is not None or body['expected_revision']!=0 or body['base_version_id'] is not None
                or response['manuscript_id'] is not None or response['expected_revision']!=0 or response['base_version_id'] is not None
                or response.get('candidate_sha256') not in (None,saved['candidate_sha256'])):
            raise ValueError('Saved successful API candidate differs from the frozen action identity or new-root scope')
        value=dict(saved,manuscript_id=body['manuscript_id'],expected_revision=body['expected_revision'])
        preview = read(self.output / kind / 'selection-preview.json')
        review = review_candidate(preview, value, body)
        review['candidate_read_evidence']=dict(source='completed_API_GET_saved_by_base_writing',
            path=str(path),canonical_json_sha256=digest(saved),
            additional_candidate_GET_performed=False,publication_source_validation='unchanged product API')
        previous = self.record.setdefault('candidate_reviews', {}).get(kind)
        if previous is not None and previous != review:
            raise ValueError('Reviewed candidate binding changed')
        self.record['candidate_reviews'][kind] = review
        self.ledger.save()
        self.write_json(kind + '/engineering-review.json', review)
        return review

    def post(self, label, path, body, **kwargs):
        if label.startswith('publish-'):
            review = self.candidate_review(label.removeprefix('publish-'))
            if body['candidate_id'] != review['candidate_id'] or body['expected_revision'] != 0:
                raise ValueError('Publication differs from reviewed candidate')
        return super().post(label, path, body, **kwargs)

    def fixed_sources(self):
        if getattr(self.args,'reuse_source_evidence',None):
            local,proof=reuse_snapshots(self.args.reuse_source_evidence,self.state['schema'])
            from app.db.database import database_connection
            from app.adapters.task_store import TaskStore
            with database_connection() as db:
                TaskStore(self.owner).require_project(db,PROJECT)
                finding=db.execute('SELECT * FROM research_finding_versions WHERE id=%s AND project_id=%s AND user_id=%s',
                    (FINDING,PROJECT,self.owner)).fetchone()
                def result(table,identity):
                    return db.execute('SELECT r.*,t.status AS resolved_task_status,t.task_type AS resolved_task_type FROM '+table+
                        ' r JOIN tasks t ON t.id=r.task_id AND t.project_id=r.project_id AND t.user_id=r.user_id WHERE r.id=%s AND r.project_id=%s AND r.user_id=%s',
                        (identity,PROJECT,self.owner)).fetchone()
                records=dict(finding=finding,figure=result('research_figure_versions',FIGURE),
                    reports={language:result('research_report_versions',identity) for language,identity in REPORTS.items()})
                signatures=check_source_records(local,records,self.owner)
            previous=self.record.setdefault('source_record_signatures',signatures)
            if previous!=signatures:raise ValueError('Fixed source records changed during this acceptance run')
            proof['current_owner_project_records_checked']=True
            proof['record_signatures']=signatures
            self.write_json('source-reuse-proof.json',proof)
            self.write_json('fixed-source-inventory.json',read(Path(self.args.reuse_source_evidence)/'fixed-source-inventory.json'))
            self.record['source_check_mode']='explicit_prior_W1_full_read_reuse_and_current_scoped_record_comparison'
            self.ledger.save()
            return local
        finding = self.get(self.base + '/research-findings/3091eea8-69e0-50d3-a34f-8b41d9dda16b/versions/' + FINDING)
        frozen = read(B04 / 'finding.json')
        if finding['id'] != FINDING or finding['sha256'] != frozen['sha256'] or finding['content'] != frozen['content']:
            raise ValueError('B04 finding differs from frozen source')
        figure = self.get(self.base + '/research-figures/' + FIGURE)
        reports = {}
        for language, identity in REPORTS.items():
            old = read(B04 / language / 'report.json')
            current = self.get(self.base + '/research-reports/' + identity)
            if (current['id'] != identity or current['sha256'] != old['sha256']
                    or current['content'] != old['content'] or current.get('task', {}).get('status') != 'succeeded'):
                raise ValueError('B04 fixed report differs or is incomplete: ' + language)
            if current['content']['finding']['id'] != FINDING:
                raise ValueError('Report finding binding differs')
            reports[language] = current
        expected_figures = {f['id']: f['manifest_sha256'] for report in reports.values() for f in report['content']['figures']}
        if (figure['id'] != FIGURE or figure.get('task', {}).get('status') != 'succeeded'
                or figure['manifest_sha256'] != expected_figures.get(FIGURE)):
            raise ValueError('B04 fixed figure binding differs or is incomplete')
        inventory = dict(finding=dict(id=FINDING, sha256=finding['sha256']),
            figure=dict(id=FIGURE, sha256=figure['manifest_sha256']),
            reports={lang: dict(id=r['id'], sha256=r['sha256']) for lang, r in reports.items()})
        self.write_json('fixed-source-inventory.json', inventory)
        return finding, figure, reports

    def run_fixed(self):
        if self.get(self.base)['project_type'] != 'research':
            raise ValueError('Expected fixed research project')
        if 'protected_before' not in self.record:
            self.record['protected_before'] = self.protected_snapshot()
            self.ledger.save()
        finding, figure, reports = self.fixed_sources()
        self.thesis_selection()
        self.writing(finding, figure, reports)
        for kind in ('sci_draft', 'thesis_draft'):
            self.candidate_review(kind)
        after = self.protected_snapshot()
        for table, rows in self.record['protected_before'].items():
            if any(after[table].get(identity) != expected for identity, expected in rows.items()):
                raise ValueError('Protected prior material changed: ' + table)
        self.fixed_sources()
        self.record.update(status='api_engineering_chain_complete' if self.args.publish else 'candidates_reviewed_publication_pending',
            protected_prior_materials_unchanged=True, fixed_source_records_unchanged=True,
            reports_regenerated=False, scientific_recompute=False, real_model_calls=0, real_network_calls=0,
            browser_acceptance='pending', word_visual_review='pending',
            school_compliance='synthetic engineering confirmation only', biological_validation='not_performed')
        self.ledger.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--qpcr-local', action='store_true', help='Only run offline saved-source context check')
    parser.add_argument('--output', type=Path, default=RUNTIME / 'a19')
    parser.add_argument('--wait-seconds', type=int, default=14400)
    parser.add_argument('--retry-original', action='append', default=[])
    parser.add_argument('--reuse-source-evidence',type=Path,
        help='Explicit prior W1 run with successful fixed-source-inventory.json; use local snapshots and current scoped records instead of extra full source GETs')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(RUNTIME.resolve()) or output == RUNTIME.resolve():
        parser.error('Use a dedicated output directory inside W1 runtime')
    if args.qpcr_local:
        if args.execute or args.publish:
            parser.error('--qpcr-local is separate from API mutation modes')
        print(json.dumps(qpcr_handoff(output / 'qpcr-context'), ensure_ascii=False))
        return
    if args.publish and not args.execute:
        parser.error('--publish requires --execute')
    if not 60 <= args.wait_seconds <= 14400:
        parser.error('Per-task observation must be 60..14400 seconds')
    import cr_b06_w1_runner as control
    state = control.read_state()
    if state['clone_status'] != 'verified' or state['source_schema'] != 'pa_test_7feb37aa74ff49c8a64d0503d0ed75f6':
        raise ValueError('Verified B06 clone of the exact accepted B04 is required')
    if not args.execute:
        print(json.dumps(dict(status='offline_prepared_not_executed', schema=state['schema'],
            project_id=PROJECT, finding_id=FINDING, figure_id=FIGURE, reports=REPORTS,
            output=str(output), new_roots_only=True, reports_regenerated=False,
            real_model_calls=0, real_network_calls=0,reuse_source_evidence=str(args.reuse_source_evidence) if args.reuse_source_evidence else None), ensure_ascii=False))
        return
    control.configure(state)
    old = read(B04 / 'receipt.json')
    selection = old['thesis_selection']
    if selection['confirmation_id'] != 'dfc82f74-82f8-4d94-86ce-52a466b36f4e' or selection['profile_revision'] != 1:
        raise ValueError('Frozen school confirmation/profile differs')
    args.thesis_selection = output / 'thesis-selection.json'
    retain(args.thesis_selection, selection)
    args.project_id, args.result_id, args.figure_result_id = PROJECT, [], []
    args.school_export_options = None
    run = W1Acceptance(args, state, output)
    try:
        run.run_fixed()
        print(json.dumps(dict(status=run.record['status'], receipt=str(run.ledger.path),
            published=run.record.get('published', []), real_model_calls=0), ensure_ascii=False))
    finally:
        run.client.close()


if __name__ == '__main__':
    main()
