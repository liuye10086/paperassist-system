"""Offline tests: all publication metadata below is explicitly synthetic."""
import json
import pytest
import requests
from app.adapters import ncbi

@pytest.fixture(autouse=True)
def postgres_schema():
    # Pure adapter tests neither need nor write a database.
    yield None

def search_data(**changes):
    result = {'count': '2', 'idlist': ['12', '34'], 'querytranslation': 'synthetic query'}
    result.update(changes)
    return json.dumps({'esearchresult': result}).encode()

XML = b'''<!DOCTYPE PubmedArticleSet SYSTEM "https://example.invalid/pubmed.dtd">
<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12</PMID><Article>
<ArticleTitle>Synthetic <i>mixed</i> &amp; title</ArticleTitle>
<Journal><Title>Invented Test Journal</Title><JournalIssue><PubDate><MedlineDate>2021 Winter</MedlineDate></PubDate></JournalIssue></Journal>
<AuthorList><Author><LastName>Example</LastName><ForeName>Ada</ForeName></Author><Author><CollectiveName>Synthetic Group</CollectiveName></Author></AuthorList>
<Abstract><AbstractText Label="METHODS">Synthetic <b>text</b>.</AbstractText></Abstract>
</Article><KeywordList><Keyword>synthetic</Keyword></KeywordList><MeshHeadingList><MeshHeading><DescriptorName>Test term</DescriptorName><QualifierName>methods</QualifierName></MeshHeading></MeshHeadingList></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="doi">10.0000/synthetic</ArticleId><ArticleId IdType="pmc">PMC123</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''

def test_module_contract_and_disabled():
    settings = ncbi.NcbiSettings()
    assert settings.enabled is False
    with pytest.raises(ncbi.NcbiError, match='ncbi_not_configured'):
        ncbi.NcbiClient(settings, session=object()).search('x',20,'relevance')

@pytest.mark.parametrize('config', [{}, {'PAPERASSIST_NCBI_ENABLED':'true'}])
def test_disabled_configuration(config, monkeypatch):
    monkeypatch.setattr(ncbi,'local_config',lambda:config)
    assert not ncbi.get_ncbi_settings().enabled

def test_identity_is_required_and_hidden(monkeypatch):
    monkeypatch.setattr(ncbi,'local_config',lambda:{'PAPERASSIST_NCBI_ENABLED':'1'})
    with pytest.raises(ncbi.NcbiError): ncbi.get_ncbi_settings()
    assert 'secret' not in repr(ncbi.NcbiSettings(True,'PaperAssist','secret@example.invalid','secret'))


def test_private_worker_identity_bundle_is_optional_bounded_and_not_reported(tmp_path,monkeypatch):
    path = tmp_path/'ncbi-config'
    path.write_text(json.dumps({'enabled':True,'tool':'PaperAssist','email':'synthetic@example.invalid','api_key':''}))
    monkeypatch.setattr(ncbi,'local_config',lambda:{'PAPERASSIST_NCBI_CONFIG_FILE':str(path)})
    assert ncbi.get_ncbi_settings().enabled
    assert ncbi.get_ncbi_settings().api_key == ''
    path.write_text('x'*16385)
    with pytest.raises(ncbi.NcbiError,match='^ncbi_not_configured$'):
        ncbi.get_ncbi_settings()

def test_search_preserves_raw_translation_and_warnings():
    data=search_data(warninglist={'phrasesignored':['synthetic warning']})
    result=ncbi.parse_search(data,20)
    assert (result.pmids,result.count,result.query_translation,result.raw)==(['12','34'],2,'synthetic query',data)
    assert result.warnings

@pytest.mark.parametrize('data', [b'{}',b'not json',search_data(count='1'),search_data(idlist=['12','12']),search_data(idlist=['evil']),search_data(errorlist={'phrasesnotfound':['secret']}),b'{"error":"secret"}'])
def test_search_rejects_invalid_or_remote_error(data):
    with pytest.raises(ncbi.NcbiError) as error: ncbi.parse_search(data,20)
    assert 'secret' not in str(error.value)

def test_article_metadata_and_statuses():
    result=ncbi.parse_fetch(XML,['12','34'])
    r=result.records[0]
    assert result.raw==XML and len(result.records)==1
    assert r['title']=='Synthetic mixed & title'
    assert r['authors']==['Ada Example','Synthetic Group']
    assert r['year']==2021 and r['publication_date']=='2021 Winter'
    assert r['abstract']==[{'label':'METHODS','text':'Synthetic text.'}]
    assert r['keywords']==['synthetic'] and r['mesh_terms']==['Test term / methods']
    assert r['full_text_links']==[{'url':'https://pmc.ncbi.nlm.nih.gov/articles/PMC123/','source':'PMC'}]
    assert r['full_text_status']=='not_acquired' and r['verification_status']=='not_verified'

def test_missing_empty_and_books():
    data=b'<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>34</PMID><ArticleTitle/><Abstract><AbstractText/></Abstract></BookDocument></PubmedBookArticle></PubmedArticleSet>'
    r=ncbi.parse_fetch(data,['34']).records[0]
    assert r['pmid']=='34' and r['year'] is None
    assert r['field_status']['title']=='empty' and r['field_status']['authors']=='missing'
    assert r['abstract_status']=='empty' and r['doi'] is None

@pytest.mark.parametrize('data', [b'<broken>',b'<wrong/>', XML.replace(b'<PMID>12',b'<PMID>99'),XML.replace(b'</PubmedArticleSet>', XML[XML.index(b'<PubmedArticle>'):XML.index(b'</PubmedArticleSet>')]+b'</PubmedArticleSet>'),b'<!DOCTYPE x [<!ENTITY e "secret">]><PubmedArticleSet>&e;</PubmedArticleSet>'])
def test_fetch_rejects_invalid_unknown_duplicate_or_entity(data):
    with pytest.raises(ncbi.NcbiError): ncbi.parse_fetch(data,['12'])

class Response:
    def __init__(self,data,status=200): self.data,self.status_code,self.closed=data,status,False
    def iter_content(self,chunk_size): yield self.data
    def close(self): self.closed=True
class Session:
    def __init__(self,response): self.response,self.calls=response,[]
    def get(self,url,**kwargs):
        self.calls.append((url,kwargs))
        if isinstance(self.response,Exception): raise self.response
        return self.response

def client(response):
    session=Session(response)
    return ncbi.NcbiClient(ncbi.NcbiSettings(True,'SyntheticTests','synthetic@example.invalid','secret'),session=session),session

def test_transport_fixed_endpoint_bounded_and_single_attempt():
    c,s=client(Response(search_data()))
    assert c.search('synthetic',20,'pub_date').count==2
    url,k=s.calls[0]
    assert url=='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi'
    assert k['allow_redirects'] is False and k['timeout']==(10,30) and k['stream'] is True
    assert len(s.calls)==1 and s.response.closed

@pytest.mark.parametrize('response,code,retryable',[(Response(b'secret',429),'ncbi_unavailable',True),(Response(b'secret',503),'ncbi_unavailable',True),(Response(b'secret',400),'ncbi_request_rejected',False),(Response(b'secret',302),'ncbi_request_rejected',False),(requests.Timeout('secret'),'ncbi_unavailable',True),(Response(b'x'*(8*1024*1024+1)),'ncbi_response_invalid',False)])
def test_transport_errors_safe(response,code,retryable):
    c,s=client(response)
    with pytest.raises(ncbi.NcbiError) as error: c.search('secret',20,'relevance')
    assert (error.value.code,error.value.retryable)==(code,retryable)
    assert 'secret' not in str(error.value) and len(s.calls)==1

@pytest.mark.parametrize('ids',[[],['x'],['12']*21,['12','12']])
def test_fetch_validates_before_network(ids):
    c,s=client(Response(XML))
    with pytest.raises(ncbi.NcbiError): c.fetch(ids)
    assert not s.calls

@pytest.mark.parametrize('limit,sort',[(1,'relevance'),(20,'evil')])
def test_search_validates_before_network(limit,sort):
    c,s=client(Response(search_data()))
    with pytest.raises(ncbi.NcbiError): c.search('synthetic',limit,sort)
    assert not s.calls

@pytest.mark.parametrize('tool,email',[('', 'synthetic@example.invalid'),('bad tool','synthetic@example.invalid'),('PaperAssist','bad'),('PaperAssist','a@b\n.invalid')])
def test_invalid_enabled_identity_never_calls_session(tool,email):
    s=Session(Response(search_data()))
    c=ncbi.NcbiClient(ncbi.NcbiSettings(True,tool,email),session=s)
    with pytest.raises(ncbi.NcbiError) as error: c.search('synthetic',20,'relevance')
    assert error.value.code=='ncbi_not_configured' and not s.calls

def test_enabled_configuration_explicit_and_immutable(monkeypatch):
    from dataclasses import FrozenInstanceError
    monkeypatch.setattr(ncbi,'local_config',lambda:{'PAPERASSIST_NCBI_ENABLED':'1','PAPERASSIST_NCBI_EMAIL':'synthetic@example.invalid'})
    settings=ncbi.get_ncbi_settings()
    assert settings.enabled and not settings.api_key
    with pytest.raises(FrozenInstanceError): settings.enabled=False

def test_fetch_transport_uses_requested_ids_and_exact_raw():
    c,s=client(Response(XML))
    result=c.fetch(['12','34'])
    assert result.raw==XML and s.calls[0][0].endswith('/efetch.fcgi')
    assert s.calls[0][1]['params']['id']=='12,34'
    assert s.response.closed

@pytest.mark.parametrize('parser,args',[(ncbi.parse_search,(20,)),(ncbi.parse_fetch,(['12'],))])
def test_cache_parsers_reject_oversized_bytes(parser,args):
    with pytest.raises(ncbi.NcbiError) as error: parser(b'x'*(8*1024*1024+1),*args)
    assert error.value.code=='ncbi_response_invalid'

def test_index_dates_never_invent_publication_year_or_abstract():
    data=b'<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12</PMID><DateCompleted><Year>2026</Year></DateCompleted><Article><Journal><JournalIssue><PubDate><Month>Oct</Month></PubDate></JournalIssue></Journal></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
    r=ncbi.parse_fetch(data,['12']).records[0]
    assert r['year'] is None and r['publication_date']=='Oct'
    assert r['abstract']==[] and r['abstract_status']=='not_returned'
    assert r['full_text_links']==[] and r['field_status']['full_text_links']=='missing'

def test_remote_xml_error_is_rejected_not_zero_results():
    with pytest.raises(ncbi.NcbiError) as error: ncbi.parse_fetch(b'<PubmedArticleSet><ERROR>secret</ERROR></PubmedArticleSet>',['12'])
    assert error.value.code=='ncbi_request_rejected' and 'secret' not in str(error.value)

def test_search_conflicting_json_keys_invalid():
    with pytest.raises(ncbi.NcbiError): ncbi.parse_search(b'{"esearchresult":{"count":"0","count":"2","idlist":[]}}',20)

@pytest.mark.parametrize('book',[False,True])
@pytest.mark.parametrize('declared',['99','bad','1234567890123'])
def test_all_declared_pubmed_identities_must_agree(book,declared):
    if book:
        data=f'<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>12</PMID></BookDocument><PubmedBookData><ArticleIdList><ArticleId IdType="pubmed">{declared}</ArticleId></ArticleIdList></PubmedBookData></PubmedBookArticle></PubmedArticleSet>'.encode()
    else:
        data=XML.replace(b'<ArticleIdList>',f'<ArticleIdList><ArticleId IdType="pubmed">{declared}</ArticleId>'.encode())
    with pytest.raises(ncbi.NcbiError) as error: ncbi.parse_fetch(data,['12'])
    assert error.value.code=='ncbi_response_invalid'

@pytest.mark.parametrize('book',[False,True])
def test_matching_declared_pubmed_identity_is_accepted(book):
    if book:
        data=b'<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>12</PMID></BookDocument><PubmedBookData><ArticleIdList><ArticleId IdType="pubmed">12</ArticleId></ArticleIdList></PubmedBookData></PubmedBookArticle></PubmedArticleSet>'
    else:
        data=XML.replace(b'<ArticleIdList>',b'<ArticleIdList><ArticleId IdType="pubmed">12</ArticleId>')
    assert ncbi.parse_fetch(data,['12']).records[0]['pmid']=='12'

def test_book_title_is_not_a_journal():
    data=b'<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>12</PMID><Book><BookTitle>Synthetic Book</BookTitle></Book></BookDocument></PubmedBookArticle></PubmedArticleSet>'
    r=ncbi.parse_fetch(data,['12']).records[0]
    assert r['journal'] is None and r['field_status']['journal']=='missing'

@pytest.mark.parametrize('pmid',['1234567890123','0','01'])
def test_malformed_provider_pmids_rejected_before_consumer_sql(pmid):
    with pytest.raises(ncbi.NcbiError): ncbi.parse_search(search_data(idlist=[pmid],count='1'),20)
    with pytest.raises(ncbi.NcbiError): ncbi.parse_fetch(XML.replace(b'<PMID>12',f'<PMID>{pmid}'.encode()),[pmid])
    c,s=client(Response(XML))
    with pytest.raises(ncbi.NcbiError): c.fetch([pmid])
    assert not s.calls


def test_version_timeout_is_consumed_by_fixed_transport():
    session = Session(Response(search_data()))
    c = ncbi.NcbiClient(ncbi.NcbiSettings(True,'PaperAssist','synthetic@example.invalid','secret'),
        session=session, timeout_seconds=3)
    assert c.search('synthetic',20,'relevance').count == 2
    assert session.calls[0][1]['timeout'] == (3,3)
    assert session.calls[0][1]['params']['tool'] == 'PaperAssist'
    for value in (0,31,True,'3'):
        with pytest.raises(ncbi.NcbiError):
            ncbi.NcbiClient(session=session, timeout_seconds=value)


def test_explicit_deployment_disable_wins_over_private_identity_file(tmp_path,monkeypatch):
    path = tmp_path/'synthetic-identity'
    path.write_text(json.dumps({'enabled':True,'tool':'PaperAssist','email':'synthetic@example.invalid','api_key':'secret'}))
    monkeypatch.setattr(ncbi,'local_config',lambda:{'PAPERASSIST_NCBI_CONFIG_FILE':str(path),'PAPERASSIST_NCBI_ENABLED':'0'})
    settings = ncbi.get_ncbi_settings()
    assert settings.enabled is False
    session = Session(Response(search_data()))
    with pytest.raises(ncbi.NcbiError):
        ncbi.NcbiClient(settings,session=session).search('synthetic',20,'relevance')
    assert session.calls == []


def test_bound_version_disabled_and_identity_revision_cannot_open_transport(monkeypatch):
    monkeypatch.setattr(ncbi,'local_config',lambda:{'PAPERASSIST_NCBI_ENABLED':'1','PAPERASSIST_NCBI_EMAIL':'synthetic@example.invalid'})
    version = {'bundle': {'ncbi': {'enabled':False,'identity':{'alias':'ncbi-default','revision':'deployment-v1'}}}}
    session = Session(Response(search_data()))
    settings = ncbi.get_ncbi_settings(version=version)
    assert settings.enabled is False
    with pytest.raises(ncbi.NcbiError):
        ncbi.NcbiClient(settings,session=session).search('synthetic',20,'relevance')
    assert session.calls == []
    for alias, revision in [('openai-default','deployment-v1'),('ncbi-default','unknown')]:
        version['bundle']['ncbi']['identity'] = {'alias':alias,'revision':revision}
        with pytest.raises(ncbi.NcbiError,match='ncbi_not_configured'):
            ncbi.get_ncbi_settings(version=version)


def test_worker_client_injection_is_only_available_in_test_environment(monkeypatch):
    from types import SimpleNamespace
    from app.domain.literature import execution
    from app.core.exceptions import StorageError
    from tests.helpers.literature import SyntheticNcbi
    repository = SimpleNamespace(config=SimpleNamespace(environment='production'))
    monkeypatch.setattr(execution,'TaskExecutionStore',lambda **kwargs:repository)
    with pytest.raises(StorageError) as error:
        execution.run_literature_task('synthetic-task',1,client=SyntheticNcbi(0))
    assert error.value.code == 'task_source_conflict'

def test_twelve_digit_pmid_is_accepted():
    assert ncbi.parse_search(search_data(idlist=['123456789012'],count='1'),20).pmids==['123456789012']

def test_conflicting_identity_in_additional_id_list_is_not_ignored():
    data=XML.replace(b'</PubmedData>',b'<ArticleIdList><ArticleId IdType="pubmed">99</ArticleId></ArticleIdList></PubmedData>')
    with pytest.raises(ncbi.NcbiError): ncbi.parse_fetch(data,['12'])


@pytest.mark.parametrize('book', [False, True])
def test_cited_pubmed_id_is_not_the_record_identity(book):
    reference=b'<ReferenceList><Reference><ArticleIdList><ArticleId IdType="pubmed">99</ArticleId></ArticleIdList></Reference></ReferenceList>'
    if book:
        data=(b'<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>12</PMID>'
              b'<ArticleIdList><ArticleId IdType="pubmed">12</ArticleId></ArticleIdList>'
              + reference + b'</BookDocument><PubmedBookData><ArticleIdList>'
              b'<ArticleId IdType="pubmed">12</ArticleId></ArticleIdList>'
              + reference + b'</PubmedBookData></PubmedBookArticle></PubmedArticleSet>')
    else:
        data=XML.replace(b'</PubmedData>',reference+b'</PubmedData>')
    assert ncbi.parse_fetch(data,['12']).records[0]['pmid']=='12'


@pytest.mark.parametrize('container', ['BookDocument', 'PubmedBookData'])
def test_conflicting_own_book_identity_is_rejected(container):
    own_id=b'<ArticleIdList><ArticleId IdType="pubmed">99</ArticleId></ArticleIdList>'
    document_id=own_id if container=='BookDocument' else b''
    book_data_id=own_id if container=='PubmedBookData' else b''
    data=(b'<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>12</PMID>'
          +document_id+b'</BookDocument><PubmedBookData>'+book_data_id
          +b'</PubmedBookData></PubmedBookArticle></PubmedArticleSet>')
    with pytest.raises(ncbi.NcbiError) as error: ncbi.parse_fetch(data,['12'])
    assert error.value.code=='ncbi_response_invalid'
