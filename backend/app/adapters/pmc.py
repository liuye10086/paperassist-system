"""Explicitly approved, sequential OAI retrieval and offline safe JATS parsing."""
import re
import time
import httpx
from defusedxml import ElementTree

ENDPOINT = 'https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/'
MAX_BYTES = 8 * 1024 * 1024
PARSER_VERSION = 2
EXCLUDED = frozenset({'fig','fig-group','supplementary-material','supplement','app','app-group','abstract','back'})


class PmcError(Exception):
    pass


def tree(raw):
    try:
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES: raise ValueError()
        root = ElementTree.fromstring(raw, forbid_entities=True, forbid_external=True)
        for node in root.iter(): node.tag = node.tag.split('}')[-1]
        pending=[(root,0)]
        while pending:
            node,depth=pending.pop()
            if depth>128: raise ValueError()
            pending.extend((child,depth+1) for child in node)
        return root
    except Exception as exc:
        raise PmcError('pmc_xml_invalid') from exc


def text(node):
    return ' '.join(''.join(node.itertext()).split())


def license_info_v1(article):
    urls=[]
    for node in article.findall('./front/article-meta/permissions/license'):
        urls.extend(v.strip() for k,v in node.attrib.items() if k.split('}')[-1]=='href')
        for link in node.iter():
            if link.tag in ('ext-link','uri'):
                urls.extend(v.strip() for k,v in link.attrib.items() if k.split('}')[-1]=='href')
                if link.text: urls.append(link.text.strip())
    accepted=[]
    for url in urls:
        match=re.fullmatch(r'https?://creativecommons\.org/(licenses/by/(1\.0|2\.0|2\.5|3\.0|4\.0)|publicdomain/zero/1\.0)/?', url)
        if match: accepted.append(dict(code='CC0-1.0' if 'publicdomain' in url else 'CC-BY-'+match[2], url=url))
        elif re.match(r'https?://creativecommons\.org/(licenses|publicdomain)/', url):
            raise PmcError('pmc_license_denied')
    if not accepted: raise PmcError('pmc_license_denied')
    if len({x['code'] for x in accepted})!=1: raise PmcError('pmc_license_denied')
    return accepted[0]


def allowed_license(url):
    match=re.fullmatch(r'https?://creativecommons\.org/(licenses/by/(1\.0|2\.0|2\.5|3\.0|4\.0)|publicdomain/zero/1\.0)/?',url)
    if match: return dict(code='CC0-1.0' if 'publicdomain' in url else 'CC-BY-'+match[2],url=url)
    if re.match(r'https?://creativecommons\.org/(licenses|publicdomain)/',url): raise PmcError('pmc_license_denied')
    return None


def data_waiver(link,parents):
    """Recognize only the explicit publisher sentence limiting this CC0 to data."""
    parent=parents.get(link)
    while parent is not None and parent.tag!='license-p': parent=parents.get(parent)
    if parent is None: return False
    marker='__PMC_DATA_LICENSE__'
    def context(node):
        if node is link: return marker
        return (node.text or '')+''.join(context(child)+(child.tail or '') for child in node)
    sentence=' '.join(context(parent).split())
    return re.search(r'(?:^|[.!?]\s+)The Creative Commons Public Domain Dedication waiver\s*\(\s*'+marker+r'\s*\)\s+applies to the data made available in this article,\s+unless otherwise stated\.(?:$|\s)',sentence,re.IGNORECASE) is not None


def license_info(article,parser_version=PARSER_VERSION):
    if parser_version==1: return license_info_v1(article)
    article_licenses=[];data_licenses=[]
    for node in article.findall('./front/article-meta/permissions/license'):
        parents={child:parent for parent in node.iter() for child in parent}
        # Structured article/text-mining refs take precedence in URL provenance;
        # every other license URL must still agree or be explicitly data-only.
        links=[n for n in node.iter() if n.tag=='license_ref']+[node]+[n for n in node.iter() if n.tag in ('ext-link','uri')]
        for link in links:
            urls=[v.strip() for k,v in link.attrib.items() if k.split('}')[-1]=='href']
            if link is not node and link.text: urls.append(link.text.strip())
            if link.tag=='license_ref' and not urls: raise PmcError('pmc_license_denied')
            for url in urls:
                value=allowed_license(url)
                if link.tag=='license_ref':
                    kind=link.get('content-type','').lower()
                    if (value is None or kind not in ('','ccbylicense','cc0license','cczerolicense')
                        or kind=='ccbylicense' and not value['code'].startswith('CC-BY-')
                        or kind in ('cc0license','cczerolicense') and value['code']!='CC0-1.0'):
                        raise PmcError('pmc_license_denied')
                if value is None: continue
                if value['code']=='CC0-1.0' and data_waiver(link,parents):
                    scoped=dict(value,scope='data')
                    if scoped not in data_licenses: data_licenses.append(scoped)
                else: article_licenses.append(value)
    if not article_licenses or len({x['code'] for x in article_licenses})!=1: raise PmcError('pmc_license_denied')
    result=dict(article_licenses[0])
    if data_licenses: result['data_licenses']=data_licenses
    return result


def eligible(node):
    if node.tag in EXCLUDED: return
    yield node
    for child in node: yield from eligible(child)


def body_text(node):
    if node.tag in EXCLUDED: return ''
    parts=[node.text or '']
    for child in node:
        parts.extend((body_text(child),child.tail or ''))
    return ''.join(parts)


def item_text(node):
    if node.tag == 'table-wrap':
        rows=[]
        for row in eligible(node):
            if row.tag!='tr': continue
            cells=[' '.join(body_text(c).split()) for c in row if c.tag in ('td','th')]
            if any(cells): rows.append(' | '.join(cells))
        return '\n'.join(rows)
    return ' '.join(body_text(node).split())


def text_at(raw, location):
    root=tree(raw)
    node=root.find(location['xml_path'])
    body=root.find('./GetRecord/record/metadata/article/body')
    if node is None or body is None or not any(n is node for n in eligible(body)): raise PmcError('pmc_xml_invalid')
    return item_text(node)


def parse_record(raw, pmcid, pmid, *, fulltext=False, parser_version=PARSER_VERSION):
    if type(parser_version) is not int or parser_version not in (1,PARSER_VERSION): raise PmcError('pmc_xml_invalid')
    root=tree(raw)
    records=root.findall('./GetRecord/record')
    if len(records)!=1 or root.tag!='OAI-PMH':
        raise PmcError('pmc_record_unavailable')
    record=records[0]
    header=record.find('./header')
    if header is None: raise PmcError('pmc_xml_invalid')
    if header.get('status')=='deleted': raise PmcError('pmc_record_unavailable')
    if record.findtext('./header/identifier')!='oai:pubmedcentral.nih.gov:'+pmcid[3:]: raise PmcError('pmc_identity_mismatch')
    articles=record.findall('./metadata/article')
    if len(articles)!=1: raise PmcError('pmc_xml_invalid')
    article=articles[0]
    identifiers={}
    for node in article.findall('./front/article-meta/article-id'):
        key=node.get('pub-id-type')
        value=text(node)
        if key in identifiers and identifiers[key]!=value: raise PmcError('pmc_identity_mismatch')
        identifiers[key]=value
    actual=identifiers.get('pmc') or identifiers.get('pmcid')
    if actual and actual.isdigit(): actual='PMC'+actual
    if actual!=pmcid or identifiers.get('pmid')!=pmid: raise PmcError('pmc_identity_mismatch')
    result=dict(pmcid=pmcid,pmid=pmid,license=license_info(article,parser_version),items=[],scope=dict(
        extracted='body paragraphs and table text only; excludes abstract, figures, supplements and back matter',
        whole_article_verified=False,paragraph_count=0,table_count=0))
    if not fulltext: return result
    body=article.find('./body')
    if body is None: raise PmcError('pmc_body_missing')
    def walk(node,path,sections):
        if node.tag in EXCLUDED: return
        if node.tag=='sec': sections=[*sections, item_text(node.find('title')) if node.find('title') is not None else '']
        if node.tag in ('p','table-wrap'):
            value=item_text(node)
            if value:
                kind='paragraph' if node.tag=='p' else 'table'
                result['items'].append(dict(id='pmc-item-'+str(len(result['items'])+1),kind=kind,text=value,
                    location=dict(xml_path=path,section=sections,xml_id=node.get('id'),kind=kind)))
                result['scope'][kind+'_count']+=1
            return
        counts={}
        for child in node:
            counts[child.tag]=counts.get(child.tag,0)+1
            walk(child,path+'/'+child.tag+'['+str(counts[child.tag])+']',sections)
    walk(body,'./GetRecord[1]/record[1]/metadata[1]/article[1]/body[1]',[])
    if not result['items']: raise PmcError('pmc_body_missing')
    return result


class PmcAdapter:
    def __init__(self, ledger, *, transport=None):
        from app.domain.literature_live import Batch06Ledger
        if type(ledger) is not Batch06Ledger: raise PmcError('pmc_not_authorized')
        if transport is not None and type(transport) is not httpx.MockTransport: raise PmcError('pmc_not_authorized')
        self.ledger=ledger
        self.source_kind='synthetic_fixture' if transport is not None else 'pmc_oai'
        self.client=httpx.Client(transport=transport,timeout=45,follow_redirects=False,trust_env=False,headers={'User-Agent':'PaperAssist/1.0 (PMC OAI public-text retrieval)'})

    def fetch(self,pmcid,pmid):
        if not re.fullmatch(r'PMC[1-9][0-9]{0,11}',pmcid) or not re.fullmatch(r'[1-9][0-9]{0,11}',pmid): raise PmcError('pmc_identity_mismatch')
        responses=[]; parsed=None; metadata=None; status='succeeded'
        # One shared ledger lock serializes all callers and spaces request starts,
        # including after restarts (reservation wall-clock times are durable).
        with self.ledger.locked() as state:
            for prefix in ('pmc_fm','pmc'):
                last=max((v['at'] for v in state['reservations'].values() if v['kind']=='pmc'),default=0)
                time.sleep(max(0,0.51-(time.time()-last)))
                entry=dict(metadata_prefix=prefix,http_status=None,raw=None,error=None,attempted=False,
                    capture_status='not_requested',received_bytes=0,retained_bytes=0,byte_limit=MAX_BYTES,admission_code=None)
                from app.domain.literature_live.policy import LivePolicyError
                try:
                    attempt=self.ledger.reserve(state,'pmc',dict(pmcid=pmcid))
                except LivePolicyError as exc:
                    if not responses: raise
                    # No HTTP occurred for this stage. Preserve the successfully
                    # acquired metadata and an explicit admission-denial entry.
                    status='pmc_request_failed';entry.update(error=status,admission_code=exc.code)
                    responses.append(entry)
                    break
                entry.update(attempted=True,capture_status='not_received')
                code='request_failed'
                retained=bytearray();received_response=False
                try:
                    with self.client.stream('GET',ENDPOINT,params=dict(verb='GetRecord',identifier='oai:pubmedcentral.nih.gov:'+pmcid[3:],metadataPrefix=prefix)) as response:
                        entry['http_status']=response.status_code
                        received_response=True;entry['capture_status']='partial'
                        for chunk in response.iter_bytes():
                            entry['received_bytes']+=len(chunk)
                            retained.extend(chunk[:max(0,MAX_BYTES-len(retained))])
                            if entry['received_bytes']>MAX_BYTES:
                                entry['capture_status']='truncated'
                                raise PmcError('pmc_response_too_large')
                        entry['raw']=bytes(retained);entry['capture_status']='complete'
                        if response.status_code!=200: raise PmcError('pmc_http_failed')
                    current=parse_record(entry['raw'],pmcid,pmid,fulltext=prefix=='pmc',parser_version=PARSER_VERSION)
                    if prefix=='pmc_fm': metadata=current
                    if parsed and current['license']['code']!=parsed['license']['code']: raise PmcError('pmc_license_denied')
                    parsed=current;code='pmc_finished'
                except (httpx.HTTPError,PmcError) as exc:
                    status=str(exc) if isinstance(exc,PmcError) else 'pmc_request_failed'
                    if isinstance(exc,httpx.HTTPError) and received_response: entry['capture_status']='partial'
                    entry['error']=status
                finally:
                    if received_response: entry['raw']=bytes(retained)
                    entry['retained_bytes']=len(retained)
                    self.ledger.finish(attempt,code=code)
                responses.append(entry)
                state=self.ledger._load(self.ledger._lock_stream)
                if status!='succeeded': break
        return dict(parser_version=PARSER_VERSION,status=status,source_kind=self.source_kind,responses=responses,
                    metadata=metadata,parsed=parsed if status=='succeeded' else None)

    def close(self): self.client.close()
