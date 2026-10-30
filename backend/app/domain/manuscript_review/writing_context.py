"""Read-only compatibility view of reconstructed science/language artifacts.

This object is server supplied, never accepted from review request JSON. It only
projects exact unchanged v2 content into the existing local numerical checker.
"""
from copy import deepcopy
from dataclasses import dataclass
from app.adapters.task_store import source_conflict

V2_WORKFLOW_MESSAGE='该版本已完成 v2 科学与语言审核。此处仅可重新检查；修改或发布请返回受控的 v2 科学与语言审核工作区。'


def has_review_edits(request):
    return any(request.get(field) for field in ('decisions','metadata','associations','corrections','selected_sources'))

@dataclass(frozen=True)
class WritingCheckContext:
    paragraphs: dict
    sources: dict
    tables: dict
    check_version: int = 1

    def exact_sources(self,ids,sources):
        return all(sid in self.sources and sources.get(sid)==self.sources[sid] for sid in ids)

    def paragraph(self,paragraph,sources):
        saved=self.paragraphs.get(paragraph['id'])
        if not saved or paragraph!=saved['paragraph'] or not self.exact_sources(paragraph.get('source_ids',[]),sources):
            raise ValueError('Paragraph differs from reconstructed scientific artifact')
        if saved.get('review_revision'):
            return paragraph['text'],deepcopy(paragraph.get('numeric_bindings',[])),[]
        projected=[];reviewed_nonstudy=[]
        signed=saved.get('numeric_version',1)==2
        from app.domain.manuscript_writing.numeric_review import value as numeric_value,checker_text
        for binding in sorted(paragraph.get('numeric_bindings',[]),key=lambda b:b['occurrence']):
            binding=deepcopy(binding)
            if signed:binding['value']=numeric_value(binding['value'])
            if binding['kind']=='study':
                sid=saved['aliases'].get(binding['source_alias'])
                if sid not in paragraph['source_ids'] or not self.exact_sources([sid],sources): raise ValueError('Study alias/source mismatch')
                projected.append(dict(fact_id='analysis_run:'+sid+':'+binding['fact_path'],value=binding['value']))
            elif binding['kind']=='literature':
                # The loader reconstructs these exact new-claim evidence bindings
                # with LiveReviewService.validate_frozen; do not invent study facts.
                projected.append(deepcopy(binding));reviewed_nonstudy.append(deepcopy(binding))
            elif binding['kind']=='context':
                context=saved.get('numeric_context',{}).get(binding['source_alias'],{})
                allowed={(item['fact_path'],numeric_value(item['value']) if signed else item['value']) for item in context.get('values',[])}
                if (saved.get('numeric_contract_version')!=2 or context.get('kind')!='provided_context'
                    or context.get('origin') not in ('user_provided','frozen_illustration') or binding.get('evidence_id') is not None
                    or (binding['fact_path'],binding['value']) not in allowed):raise ValueError('Context differs from its original frozen science catalog')
                # Typed authority comes from the exact scientific artifact, not a
                # statistical fact or a literature-support decision.
                projected.append(deepcopy(binding));reviewed_nonstudy.append(deepcopy(binding))
            else:
                raise ValueError('Unknown reconstructed numeric decision kind')
        return checker_text(saved['text']) if signed else saved['text'],projected,reviewed_nonstudy

    def table(self,path,table,sources):
        saved=self.tables.get(path)
        if not saved or table!=saved['approved'] or table['source_ids']!=saved['original']['source_ids'] or not self.exact_sources(table['source_ids'],sources):
            raise ValueError('Table differs from its exact language artifact')
        return saved['original']['rows'],saved['language']


def load_writing_context(manuscripts,db,project,identity,snapshot,*,check_version=2):
    """Load owner-scoped authoritative artifacts, including retained rewrite prose."""
    if type(check_version) is not int or check_version not in (1,2):raise source_conflict()
    if snapshot.get('user_return_provenance'):
        from app.domain.review_rounds.returns import user_return_writing_context
        return user_return_writing_context(manuscripts,db,project,identity,snapshot,check_version=check_version)
    if snapshot.get('review_revision_provenance'):
        from app.domain.review_rounds.revisions import revision_writing_context
        return revision_writing_context(manuscripts,db,project,identity,snapshot,check_version=check_version)
    if snapshot.get('writing_provenance',{}).get('schema_version')!=2: return None
    from app.domain.manuscript_writing.live_review import LiveReviewService
    from app.domain.manuscript_writing.language_service import LanguageReviewService
    from app.domain.manuscript_writing.authorization import LiveWritingService
    from app.domain.manuscript_writing.numeric_contract import is_numeric_v2
    reviews=LiveReviewService(manuscripts.assets);paragraphs={};seen=set();current=snapshot;approved=None
    while current.get('writing_provenance',{}).get('schema_version')==2:
        provenance=current['writing_provenance'];request_id=provenance['request_id']
        if request_id in seen: raise source_conflict()
        seen.add(request_id)
        review=reviews.row(db,project,identity,request_id,provenance['review_id'])
        reviews.validate_frozen(db,project,identity,request_id,review)
        if provenance.get('language_review_id'):
            language=LanguageReviewService(manuscripts.assets).language_row(db,project,identity,request_id,provenance['language_review_id'])
            if language['review_id']!=review['id']: raise source_conflict()
            exact=language['candidate_json']
        else: exact=review['reviewed_candidate_json']
        if approved is None: approved=exact
        raw,task=reviews.raw(db,project,identity,request_id);frozen=task['input_snapshot']
        bundle=LiveWritingService(manuscripts.assets).bundle(db,project,frozen['execution']['bundle_id'])
        saved={p['id']:p for s in exact['sections'] for p in s['paragraphs']}
        original={p['id']:p for s in raw['candidate_json']['sections'] for p in s['paragraphs']}
        for decision in review['request_json']['paragraphs']:
            pid=decision['paragraph_id']
            paragraphs.setdefault(pid,dict(paragraph=deepcopy(saved[pid]),aliases=deepcopy(bundle['local_manifest']['sources']),
                text=decision['corrected_text'] if decision['corrected_text'] is not None else original[pid]['text'],
                numeric_version=review['report_json'].get('numeric_validation_version',1) if check_version==2 else 1,
                **(dict(numeric_contract_version=2,numeric_context=deepcopy(bundle['local_manifest'].get('numeric_context',{}))) if is_numeric_v2(bundle) else {})))
        current=frozen['base_snapshot']
    # T2 preserves all frozen result groups. T3 reconstructs only explicit bound
    # display edits. Compare the original source rows before applying that view.
    originals={t['id']:t for g in current['results_groups'] for t in g['tables']}
    tables={}
    for g,group in enumerate(approved['results_groups']):
        for t,table in enumerate(group['tables']):
            if table['id'] not in originals: raise source_conflict()
            tables[f'/results_groups/{g}/tables/{t}']=dict(original=deepcopy(originals[table['id']]),language=current['output_language'],approved=deepcopy(table))
    return WritingCheckContext(paragraphs=paragraphs,sources={s['id']:deepcopy(s) for s in approved['sources']},tables=tables,check_version=check_version)
