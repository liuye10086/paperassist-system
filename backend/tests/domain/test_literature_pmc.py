"""Offline OAI/JATS safety and precise parsed scope."""
import pytest
import httpx


def xml(*, pmcid='PMC123', pmid='990000002', license='https://creativecommons.org/licenses/by/4.0/', body=True):
    text = '<body><sec><title>Results</title><p>Actual <italic>body</italic> text.</p><table-wrap id="t1"><table><tr><td>Cell A</td><td>Cell B</td></tr></table></table-wrap></sec></body>' if body else ''
    return (f'<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/"><GetRecord><record><header><identifier>oai:pubmedcentral.nih.gov:{pmcid[3:]}</identifier></header><metadata><article><front><article-meta><article-id pub-id-type="pmc">{pmcid}</article-id><article-id pub-id-type="pmid">{pmid}</article-id><permissions><license xmlns:xlink="http://www.w3.org/1999/xlink" xlink:href="{license}">License</license></permissions><abstract><p>Abstract only.</p></abstract></article-meta></front>{text}</article></metadata></record></GetRecord></OAI-PMH>').encode()


def module():
    import importlib.util
    assert importlib.util.find_spec('app.adapters.pmc') is not None, 'PMC adapter is required'
    from app.adapters import pmc
    return pmc


@pytest.mark.parametrize('url', ['', 'https://creativecommons.org/licenses/by-nc/4.0/', 'https://creativecommons.org/licenses/by-nd/4.0/', 'https://creativecommons.org/licenses/by-sa/4.0/', 'https://evil.test/licenses/by/4.0/'])
def test_license_missing_or_not_allowed(url):
    pmc = module()
    with pytest.raises(pmc.PmcError, match='pmc_license_denied'):
        pmc.parse_record(xml(license=url), 'PMC123', '990000002')


@pytest.mark.parametrize('url,code',[('https://creativecommons.org/publicdomain/zero/1.0/','CC0-1.0'),('http://creativecommons.org/licenses/by/2.5/','CC-BY-2.5')])
def test_explicit_cc0_and_cc_by_versions(url,code):
    assert module().parse_record(xml(license=url),'PMC123','990000002')['license']==dict(code=code,url=url)


@pytest.mark.parametrize('kwargs', [dict(pmcid='PMC124'), dict(pmid='990000003')])
def test_identity_mismatch(kwargs):
    pmc = module()
    with pytest.raises(pmc.PmcError, match='pmc_identity_mismatch'):
        pmc.parse_record(xml(**kwargs), 'PMC123', '990000002')


def test_external_entities_rejected_but_common_doctype_allowed():
    pmc = module()
    raw = b'<!DOCTYPE OAI-PMH SYSTEM "https://never.test/jats.dtd">' + xml()
    parsed = pmc.parse_record(raw, 'PMC123', '990000002', fulltext=True)
    assert parsed['items'][0]['text'] == 'Actual body text.'
    malicious = b'<!DOCTYPE OAI-PMH [<!ENTITY xxe SYSTEM "file:///private">]>' + xml().replace(b'Actual ', b'&xxe; ')
    with pytest.raises(pmc.PmcError, match='pmc_xml_invalid'):
        pmc.parse_record(malicious, 'PMC123', '990000002', fulltext=True)


def test_abstract_is_never_fulltext_and_coordinates_reconstruct():
    pmc = module()
    with pytest.raises(pmc.PmcError, match='pmc_body_missing'):
        pmc.parse_record(xml(body=False), 'PMC123', '990000002', fulltext=True)
    result = pmc.parse_record(xml(), 'PMC123', '990000002', fulltext=True)
    assert [i['kind'] for i in result['items']] == ['paragraph', 'table']
    assert result['items'][1]['text'] == 'Cell A | Cell B'
    for item in result['items']:
        assert pmc.text_at(xml(), item['location']) == item['text']
        assert item['location']['section'] == ['Results']
    assert result['scope']['whole_article_verified'] is False


def test_missing_oai_header_is_a_saved_invalid_response(tmp_path,postgres_schema):
    pmc=module()
    from app.domain.literature_live import Batch06Ledger
    ledger=Batch06Ledger(tmp_path/'ledger.jsonl',batch_id='bad-header',schema=postgres_schema.schema,public_inputs=[],pmcids=['PMC123'])
    raw=xml().replace(b'<header>',b'<absent>').replace(b'</header>',b'</absent>')
    adapter=pmc.PmcAdapter(ledger,transport=httpx.MockTransport(lambda req:httpx.Response(200,content=raw)))
    result=adapter.fetch('PMC123','990000002')
    assert result['status']=='pmc_xml_invalid' and result['responses'][0]['raw']==raw


def test_excessive_xml_depth_is_rejected_as_invalid():
    pmc=module()
    raw=xml().replace(b'<body>',b'<body>'+b'<sec>'*1200).replace(b'</body>',b'</sec>'*1200+b'</body>')
    with pytest.raises(pmc.PmcError,match='pmc_xml_invalid'):
        pmc.parse_record(raw,'PMC123','990000002',fulltext=True)


def test_comparison_cannot_conclude_from_one_reference():
    from app.domain.literature_assistance.contracts import validate_result
    snapshot=dict(input=dict(kind='evidence_comparison',evidence_ids=['a','b']),material=dict(evidence=[
        dict(id='a',project_reference_id='one',reading_scope='pmc_fulltext'),dict(id='b',project_reference_id='two',reading_scope='abstract')]))
    result=dict(status='unsupported',relevance='related',reason='No support',narrowed_statement='',limitations=['Excerpts only'],evidence_ids=['a'],comparison='consistent')
    with pytest.raises(ValueError): validate_result(result,snapshot)


def test_old_quote_request_dump_has_exact_historic_keys():
    from app.domain.literature_evidence.contracts import QuoteRequest
    old=dict(claim_revision=1,project_reference_id='reference',source_kind='abstract',search_id='search',material_id=None,item_id=None,quote='Actual abstract')
    assert QuoteRequest.model_validate(old).model_dump(mode='json')==old


def test_adapter_reserves_each_request_and_stops_after_denied_metadata(tmp_path, postgres_schema):
    pmc = module()
    from app.domain.literature_live import Batch06Ledger
    ledger = Batch06Ledger(tmp_path/'ledger.jsonl', batch_id='test-pmc', schema=postgres_schema.schema, public_inputs=[], pmcids=['PMC123'])
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=xml(license=''))
    adapter = pmc.PmcAdapter(ledger, transport=httpx.MockTransport(handler))
    result = adapter.fetch('PMC123', '990000002')
    assert result['status'] == 'pmc_license_denied' and len(result['responses']) == 1
    assert len(calls)==1 and calls[0].url.params['metadataPrefix']=='pmc_fm'
    assert ledger.summary()['pmc_attempts']==1
    with pytest.raises(Exception): adapter.fetch('PMC999', '990000002')
    assert len(calls)==1


def test_adapter_keeps_failed_http_and_two_raw_receipts(tmp_path, postgres_schema):
    pmc = module()
    from app.domain.literature_live import Batch06Ledger
    ledger = Batch06Ledger(tmp_path/'ledger.jsonl', batch_id='test-pmc', schema=postgres_schema.schema, public_inputs=[], pmcids=['PMC123'])
    adapter = pmc.PmcAdapter(ledger, transport=httpx.MockTransport(lambda req: httpx.Response(503, content=b'actual failure')))
    result = adapter.fetch('PMC123', '990000002')
    assert result['status']=='pmc_http_failed' and result['responses'][0]['raw']==b'actual failure'
    adapter.close()
    adapter = pmc.PmcAdapter(ledger, transport=httpx.MockTransport(lambda req: httpx.Response(200, content=xml())))
    result=adapter.fetch('PMC123', '990000002')
    assert result['status']=='succeeded' and len(result['responses'])==2
    assert ledger.summary()['pmc_attempts']==3
