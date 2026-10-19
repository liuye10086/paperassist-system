"""Offline actual exported metadata and conservative article/data license scope."""
import hashlib
import json
from pathlib import Path
import pytest
from app.adapters.pmc import parse_record,PmcError
from tests.domain.test_literature_pmc import xml

INPUTS=Path(__file__).resolve().parents[1]/'fixtures/pmc_license_versions'
MANIFEST=json.loads((INPUTS/'manifest.json').read_text(encoding='utf-8'))


def actual(identity):
    entry=next(row for row in MANIFEST if row['pmcid']==identity)
    raw=(INPUTS/(identity+'.xml')).read_bytes()
    assert hashlib.sha256(raw).hexdigest()==entry['sha256']
    return entry,raw


def test_actual_article_cc_by_and_data_cc0_are_distinct_scopes():
    entry,raw=actual('PMC6827248')
    parsed=parse_record(raw,entry['pmcid'],entry['pmid'])
    assert parsed['license']['code']=='CC-BY-4.0'
    assert parsed['license']['url']=='https://creativecommons.org/licenses/by/4.0/'
    assert parsed['license']['data_licenses']==[dict(code='CC0-1.0',url='http://creativecommons.org/publicdomain/zero/1.0/',scope='data')]


@pytest.mark.parametrize('identity',['PMC12529328','PMC6827248','PMC12085591'])
def test_actual_historical_v1_license_denials_are_unchanged(identity):
    entry,raw=actual(identity)
    with pytest.raises(PmcError,match='pmc_license_denied'):
        parse_record(raw,entry['pmcid'],entry['pmid'],parser_version=1)


@pytest.mark.parametrize('identity',['PMC12529328','PMC12085591'])
def test_actual_restricted_articles_remain_denied_v2(identity):
    entry,raw=actual(identity)
    with pytest.raises(PmcError,match='pmc_license_denied'):
        parse_record(raw,entry['pmcid'],entry['pmid'])


def licensed(content):
    start=xml().split(b'<permissions>')[0]
    end=xml().split(b'</permissions>')[1]
    return start+b'<permissions><license xmlns:ali="http://www.niso.org/schemas/ali/1.0/" xmlns:xlink="http://www.w3.org/1999/xlink">'+content.encode()+b'</license></permissions>'+end


@pytest.mark.parametrize('kind',['by-nc','by-nd','by-sa','by-nc-nd'])
def test_restricted_license_ref_is_not_ignored(kind):
    raw=licensed(f'<ali:license_ref>https://creativecommons.org/licenses/{kind}/4.0/</ali:license_ref><license-p><ext-link xlink:href="https://creativecommons.org/licenses/by/4.0/"/></license-p>')
    with pytest.raises(PmcError,match='pmc_license_denied'): parse_record(raw,'PMC123','990000002')


@pytest.mark.parametrize('extra',[
    '<ext-link xlink:href="https://creativecommons.org/publicdomain/zero/1.0/"/>',
    '<ext-link xlink:href="https://creativecommons.org/licenses/by/3.0/"/>',
    '<ext-link xlink:href="https://creativecommons.org/licenses/by-nc/4.0/"/>',
    'The Creative Commons Public Domain Dedication waiver (<ext-link xlink:href="http://creativecommons.org/publicdomain/zero/1.0/"/>) applies to this article.',
])
def test_ambiguous_or_conflicting_article_license_is_not_waived(extra):
    raw=licensed('<ali:license_ref content-type="ccbylicense">https://creativecommons.org/licenses/by/4.0/</ali:license_ref><license-p>'+extra+'</license-p>')
    with pytest.raises(PmcError,match='pmc_license_denied'): parse_record(raw,'PMC123','990000002')


def test_data_cc0_declaration_alone_cannot_authorize_article():
    raw=licensed('<license-p>The Creative Commons Public Domain Dedication waiver (<ext-link xlink:href="http://creativecommons.org/publicdomain/zero/1.0/"/>) applies to the data made available in this article, unless otherwise stated.</license-p>')
    with pytest.raises(PmcError,match='pmc_license_denied'): parse_record(raw,'PMC123','990000002')
