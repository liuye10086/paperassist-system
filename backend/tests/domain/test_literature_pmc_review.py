"""Focused offline regressions for the three important review findings."""
import httpx
import pytest
from tests.domain.test_literature_pmc import xml


def reserve(ledger,count):
    with ledger.locked() as state:
        for _ in range(count):
            attempt=ledger.reserve(state,'pmc',dict(pmcid='PMC123'))
            ledger.finish(attempt,code='pmc_finished')


def test_twelfth_metadata_is_retained_when_body_admission_fails(tmp_path,postgres_schema):
    from app.adapters.pmc import PmcAdapter
    from app.domain.literature_live import Batch06Ledger
    ledger=Batch06Ledger(tmp_path/'ledger',batch_id='review',schema=postgres_schema.schema,public_inputs=[],pmcids=['PMC123'])
    reserve(ledger,11);calls=[]
    def handle(req):
        calls.append(req)
        return httpx.Response(200,content=xml())
    adapter=PmcAdapter(ledger,transport=httpx.MockTransport(handle))
    result=adapter.fetch('PMC123','990000002')
    assert result['status']=='pmc_request_failed'
    assert result['metadata']['license']['code']=='CC-BY-4.0'
    assert result['responses'][0]['raw']==xml()
    denied=result['responses'][1]
    assert denied['attempted'] is False and denied['capture_status']=='not_requested'
    assert denied['admission_code']=='live_budget_exhausted' and denied['raw'] is None
    assert len(calls)==1 and ledger.summary()['pmc_attempts']==12


class Interrupted(httpx.SyncByteStream):
    def __iter__(self):
        yield xml()
        raise httpx.ReadTimeout('synthetic interruption')


@pytest.mark.parametrize('kind',['partial','truncated'])
def test_incomplete_body_retains_bounded_bytes_and_never_parses(tmp_path,postgres_schema,kind):
    from app.adapters.pmc import PmcAdapter,MAX_BYTES
    from app.domain.literature_live import Batch06Ledger
    ledger=Batch06Ledger(tmp_path/'ledger',batch_id='review',schema=postgres_schema.schema,public_inputs=[],pmcids=['PMC123'])
    def handle(req):
        if req.url.params['metadataPrefix']=='pmc_fm': return httpx.Response(200,content=xml())
        return httpx.Response(200,stream=Interrupted()) if kind=='partial' else httpx.Response(200,content=b'x'*(MAX_BYTES+17))
    result=PmcAdapter(ledger,transport=httpx.MockTransport(handle)).fetch('PMC123','990000002')
    body=result['responses'][1]
    assert body['raw'] is not None
    assert body['capture_status']==kind and body['attempted'] is True
    assert body['retained_bytes']==len(body['raw'])<=MAX_BYTES
    assert body['received_bytes']==(len(xml()) if kind=='partial' else MAX_BYTES+17)
    assert body['byte_limit']==MAX_BYTES
    assert body['raw']==(xml() if kind=='partial' else b'x'*MAX_BYTES)
    assert result['status']==('pmc_request_failed' if kind=='partial' else 'pmc_response_too_large')
    assert result['parsed'] is None and result['metadata'] is not None
    assert ledger.summary()['pmc_attempts']==2


@pytest.mark.parametrize('container',['fig','supplementary-material','app','abstract'])
def test_excluded_only_body_cannot_be_fulltext(container):
    from app.adapters.pmc import parse_record,PmcError,text_at
    raw=xml().replace(b'<body>',b'<body><'+container.encode()+b'>').replace(b'</body>',b'</'+container.encode()+b'></body>')
    with pytest.raises(PmcError,match='pmc_body_missing'):
        parse_record(raw,'PMC123','990000002',fulltext=True)
    with pytest.raises(PmcError,match='pmc_xml_invalid'):
        text_at(raw,dict(xml_path='./GetRecord/record/metadata/article/body/'+container+'/sec/p'))


def test_nested_exclusions_remove_text_but_keep_tail_and_reconstruct():
    from app.adapters.pmc import parse_record,text_at
    raw=xml().replace(b'Actual <italic>body</italic> text.',b'Actual <italic>body<fig><caption><p>secret figure</p></caption></fig></italic> text.<supplementary-material><p>secret supplement</p></supplementary-material> Tail.')
    raw=raw.replace(b'Cell A',b'Cell A<fig><p>secret cell</p></fig> tail')
    parsed=parse_record(raw,'PMC123','990000002',fulltext=True)
    assert parsed['items'][0]['text']=='Actual body text. Tail.'
    assert parsed['items'][1]['text']=='Cell A tail | Cell B'
    for item in parsed['items']:
        assert 'secret' not in item['text']
        assert text_at(raw,item['location'])==item['text']


def test_table_with_only_excluded_figures_is_not_body_text():
    from app.adapters.pmc import parse_record,PmcError
    prefix=xml().split(b'<body>')[0]
    suffix=xml().split(b'</body>')[1]
    raw=prefix+b'<body><table-wrap><table><tr><td><fig><p>caption</p></fig></td><td><supplementary-material><p>supplement</p></supplementary-material></td></tr></table></table-wrap></body>'+suffix
    with pytest.raises(PmcError,match='pmc_body_missing'):
        parse_record(raw,'PMC123','990000002',fulltext=True)
