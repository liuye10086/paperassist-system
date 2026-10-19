"""Bounded, single-attempt NCBI transport and deterministic offline parsers."""
from dataclasses import dataclass, field
import json
import re
from pathlib import Path
import requests
from defusedxml import ElementTree
from app.core.config import local_config

MAX_BYTES = 8 * 1024 * 1024
BASE_URL = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'

class NcbiError(Exception):
    def __init__(self, code, *args, retryable=None):
        allowed = {'ncbi_not_configured', 'ncbi_unavailable', 'ncbi_request_rejected', 'ncbi_response_invalid'}
        self.code = code if code in allowed else 'ncbi_response_invalid'
        self.retryable = self.code == 'ncbi_unavailable' if retryable is None else bool(retryable)
        super().__init__(self.code)

@dataclass(frozen=True)
class NcbiSettings:
    enabled: bool = False
    tool: str = 'PaperAssist'
    email: str = field(default='', repr=False)
    api_key: str = field(default='', repr=False)

def _identity(settings):
    if not settings.enabled or not isinstance(settings.tool, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', settings.tool) or not isinstance(settings.email, str) or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', settings.email):
        raise NcbiError('ncbi_not_configured')

def get_ncbi_settings():
    config = local_config()
    if config.get('PAPERASSIST_NCBI_CONFIG_FILE'):
        from app.core.paths import BACKEND_ROOT
        try:
            path = BACKEND_ROOT / Path(config['PAPERASSIST_NCBI_CONFIG_FILE']).expanduser()
            with path.open('rb') as stream: raw = stream.read(16385)
            if len(raw)>16384: raise ValueError()
            values = json.loads(raw)
            if (set(values) != {'enabled','tool','email','api_key'} or type(values['enabled']) is not bool
                    or any(not isinstance(values[k],str) for k in ('tool','email','api_key'))):
                raise ValueError()
            settings = NcbiSettings(**values)
        except (OSError,ValueError,TypeError):
            raise NcbiError('ncbi_not_configured') from None
    else:
        settings = NcbiSettings(config.get('PAPERASSIST_NCBI_ENABLED') == '1', config.get('PAPERASSIST_NCBI_TOOL') or 'PaperAssist', config.get('PAPERASSIST_NCBI_EMAIL') or '', config.get('PAPERASSIST_NCBI_API_KEY') or '')
    if settings.enabled:
        _identity(settings)
    return settings

@dataclass(frozen=True)
class SearchResult:
    pmids: list[str]
    count: int
    query_translation: str | None
    warnings: list[str]
    raw: bytes = field(repr=False)

@dataclass(frozen=True)
class FetchResult:
    records: list[dict]
    raw: bytes = field(repr=False)

def _bytes(data):
    if not isinstance(data, bytes) or len(data) > MAX_BYTES:
        raise NcbiError('ncbi_response_invalid')

def _ids(pmids):
    return isinstance(pmids, list) and all(isinstance(p, str) and re.fullmatch(r'[1-9][0-9]{0,11}', p) for p in pmids) and len(set(pmids)) == len(pmids)

def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result

def parse_search(data: bytes, limit: int):
    _bytes(data)
    try:
        if type(limit) is not int or limit not in (20, 50, 100):
            raise ValueError()
        body = json.loads(data, object_pairs_hook=_json_object)
        if not isinstance(body, dict):
            raise ValueError()
        result = body.get('esearchresult')
        if body.get('error') or (isinstance(result, dict) and (result.get('error') or result.get('errorlist'))):
            raise NcbiError('ncbi_request_rejected')
        if not isinstance(result, dict):
            raise ValueError()
        ids = result['idlist']
        count_raw = result['count']
        if not _ids(ids) or not isinstance(count_raw, str) or not count_raw.isdecimal():
            raise ValueError()
        count = int(count_raw)
        if count < len(ids) or len(ids) > limit:
            raise ValueError()
        translation = result.get('querytranslation')
        if translation is not None and not isinstance(translation, str):
            raise ValueError()
        warning = result.get('warninglist', {})
        if not isinstance(warning, dict) or any(not isinstance(v, list) or any(not isinstance(w, str) for w in v) for v in warning.values()):
            raise ValueError()
        return SearchResult(ids, count, translation, [w for values in warning.values() for w in values], data)
    except NcbiError:
        raise
    except Exception:
        raise NcbiError('ncbi_response_invalid') from None

def _text(node):
    return ''.join(node.itertext()).strip() if node is not None else None

def _one(node, path):
    return _text(node.find(path))

def _record(node, book=False):
    citation = node.find('BookDocument' if book else 'MedlineCitation')
    if citation is None:
        raise ValueError()
    id_nodes = citation.findall('PMID')
    if len(id_nodes) != 1:
        raise ValueError()
    pmid = _text(id_nodes[0])
    article = citation if book else citation.find('Article')
    if article is None:
        raise ValueError()
    title = _one(article, 'ArticleTitle')
    author_list = article.find('AuthorList')
    authors = []
    for author in article.findall('AuthorList/Author'):
        collective = _one(author, 'CollectiveName')
        name = collective or ' '.join(filter(None, [_one(author, 'ForeName') or _one(author, 'Initials'), _one(author, 'LastName'), _one(author, 'Suffix')]))
        if name:
            authors.append(name)
    date_node = article.find('Book/PubDate' if book else 'Journal/JournalIssue/PubDate')
    publication_date = None
    year = None
    if date_node is not None:
        supplied_year = _one(date_node, 'Year')
        medline = _one(date_node, 'MedlineDate')
        publication_date = medline if medline is not None else ' '.join(filter(None, [_text(child) for child in date_node]))
        year_match = re.match(r'^([12][0-9]{3})(?:\b|$)', supplied_year or medline or '')
        if year_match:
            year = int(year_match[1])
    journal = None if book else _one(article, 'Journal/Title')
    id_list = node.find('PubmedBookData/ArticleIdList' if book else 'PubmedData/ArticleIdList')
    identity_paths = ('BookDocument/ArticleIdList', 'PubmedBookData/ArticleIdList') if book else ('PubmedData/ArticleIdList',)
    declared_pmids = [
        _text(article_id)
        for path in identity_paths
        for identity_list in node.findall(path)
        for article_id in identity_list.findall('ArticleId')
        if article_id.get('IdType') == 'pubmed'
    ]
    if any(not _ids([declared]) or declared != pmid for declared in declared_pmids):
        raise ValueError()
    ids = {} if id_list is None else {kind: [_text(e) for e in id_list.findall('ArticleId') if e.get('IdType') == kind] for kind in ('doi', 'pmc')}
    if any(len(set(v)) > 1 for v in ids.values()):
        raise ValueError()
    doi = next(iter(ids.get('doi', [])), None)
    abstract_node = article.find('Abstract')
    abstract = [{'label': e.get('Label'), 'text': _text(e)} for e in article.findall('Abstract/AbstractText')]
    keywords = list(filter(None, [_text(e) for e in citation.findall('KeywordList/Keyword')]))
    mesh = [' / '.join(filter(None, [_one(e, 'DescriptorName')] + [_text(q) for q in e.findall('QualifierName')])) for e in citation.findall('MeshHeadingList/MeshHeading')]
    mesh = list(filter(None, mesh))
    links = [{'url': f'https://pmc.ncbi.nlm.nih.gov/articles/{p}/', 'source': 'PMC'} for p in ids.get('pmc', []) if p and re.fullmatch(r'PMC[1-9][0-9]*', p)]
    values = dict(title=title, authors=authors, year=year, journal=journal, doi=doi, abstract=abstract, keywords=keywords, mesh_terms=mesh, full_text_links=links)
    present_nodes = dict(title=article.find('ArticleTitle'), authors=author_list, year=date_node, journal=None if book else article.find('Journal/Title'), doi=None if not ids.get('doi') else id_list, abstract=abstract_node, keywords=citation.find('KeywordList'), mesh_terms=citation.find('MeshHeadingList'), full_text_links=None if not ids.get('pmc') else id_list)
    statuses = {k: ('present' if v and (k != 'abstract' or any(a['text'] for a in v)) else 'missing' if present_nodes[k] is None else 'empty') for k, v in values.items()}
    return dict(pmid=pmid, pubmed_url=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/', publication_date=publication_date, **values, field_status=statuses, abstract_status='not_returned' if abstract_node is None else 'available' if any(a['text'] for a in abstract) else 'empty', full_text_status='not_acquired', verification_status='not_verified', doi_resolution_status='not_checked')

def parse_fetch(data: bytes, pmids: list[str]):
    _bytes(data)
    try:
        if not _ids(pmids) or not 1 <= len(pmids) <= 20:
            raise ValueError()
        root = ElementTree.fromstring(data, forbid_dtd=False, forbid_entities=True, forbid_external=True)
        if root.tag == 'ERROR' or root.find('.//ERROR') is not None:
            raise NcbiError('ncbi_request_rejected')
        if root.tag != 'PubmedArticleSet':
            raise ValueError()
        records = []
        seen = set()
        for node in root:
            if node.tag not in ('PubmedArticle', 'PubmedBookArticle'):
                raise ValueError()
            record = _record(node, node.tag == 'PubmedBookArticle')
            pmid = record['pmid']
            if pmid not in pmids or pmid in seen:
                raise ValueError()
            seen.add(pmid)
            records.append(record)
        return FetchResult(records, data)
    except NcbiError:
        raise
    except Exception:
        raise NcbiError('ncbi_response_invalid') from None

class NcbiClient:
    def __init__(self, settings=None, *, session=None):
        self.settings = settings if settings is not None else get_ncbi_settings()
        self.session = session if session is not None else requests.Session()

    def _get(self, endpoint, params):
        _identity(self.settings)
        params = {**params, 'tool': self.settings.tool, 'email': self.settings.email}
        if self.settings.api_key:
            params['api_key'] = self.settings.api_key
        response = None
        try:
            response = self.session.get(BASE_URL + endpoint, params=params, timeout=(10, 30), allow_redirects=False, stream=True)
            status = response.status_code
            if status == 429 or 500 <= status <= 599:
                raise NcbiError('ncbi_unavailable')
            if status != 200:
                raise NcbiError('ncbi_request_rejected')
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise NcbiError('ncbi_response_invalid')
                chunks.append(chunk)
            return b''.join(chunks)
        except NcbiError:
            raise
        except requests.RequestException:
            raise NcbiError('ncbi_unavailable') from None
        finally:
            if response is not None:
                response.close()

    def search(self, query: str, limit: int, sort: str):
        _identity(self.settings)
        if not isinstance(query, str) or not query.strip() or len(query) > 10000 or type(limit) is not int or limit not in (20, 50, 100) or sort not in ('relevance', 'pub_date'):
            raise NcbiError('ncbi_request_rejected')
        return parse_search(self._get('esearch.fcgi', {'db':'pubmed', 'term':query, 'retmax':limit, 'retmode':'json', 'sort':sort}), limit)

    def fetch(self, pmids: list[str]):
        _identity(self.settings)
        if not _ids(pmids) or not 1 <= len(pmids) <= 20:
            raise NcbiError('ncbi_request_rejected')
        return parse_fetch(self._get('efetch.fcgi', {'db':'pubmed', 'id':','.join(pmids), 'retmode':'xml', 'rettype':'abstract'}), pmids)
