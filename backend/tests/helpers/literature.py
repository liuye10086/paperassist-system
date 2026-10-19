"""Explicitly synthetic PubMed-shaped bytes; never real research material."""
import json
from xml.sax.saxutils import escape

from app.adapters.ncbi import NcbiError, parse_fetch, parse_search


class SyntheticNcbi:
    source_kind = 'synthetic_fixture'

    def __init__(self, count=25, *, suffix='', fail_fetches=0, omit=()):
        self.count = count
        self.suffix = suffix
        self.fail_fetches = fail_fetches
        self.omit = set(omit)
        self.calls = []
        self.ids = [str(990000001 + n) for n in range(count)]

    def search(self, query, limit, sort):
        self.calls.append(('esearch', query, limit, sort))
        return parse_search(json.dumps({'esearchresult': {'count': str(self.count),
            'idlist': self.ids[:limit], 'querytranslation': query}}).encode(), limit)

    def fetch(self, pmids):
        self.calls.append(('efetch', list(pmids)))
        if self.fail_fetches:
            self.fail_fetches -= 1
            raise NcbiError('ncbi_unavailable')
        records = []
        for pmid in pmids:
            if pmid in self.omit:
                continue
            number = int(pmid) - 990000001
            year = '<PubDate><Year>2024</Year></PubDate>' if number % 3 else '<PubDate/>'
            abstract = '' if number % 4 == 0 else '<Abstract><AbstractText Label="PURPOSE">Synthetic protocol fixture; this is not a research finding.</AbstractText></Abstract>'
            identifiers = '<ArticleId IdType="pubmed">' + pmid + '</ArticleId>'
            if number % 2:
                identifiers += '<ArticleId IdType="doi">10.0000/synthetic-' + pmid + '</ArticleId>'
            records.append(f'<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article><ArticleTitle>Synthetic record {pmid} {escape(self.suffix)}</ArticleTitle><Journal><Title>Synthetic fixture journal</Title><JournalIssue>{year}</JournalIssue></Journal><AuthorList><Author><CollectiveName>Synthetic testing group</CollectiveName></Author></AuthorList>{abstract}</Article></MedlineCitation><PubmedData><ArticleIdList>{identifiers}</ArticleIdList></PubmedData></PubmedArticle>')
        raw = ('<?xml version="1.0"?><PubmedArticleSet>' + ''.join(records) + '</PubmedArticleSet>').encode()
        return parse_fetch(raw, pmids)
