"""Test-only synthetic OCR and provider denial for a real isolated Worker.

The parent OCR is deliberately injected, including its artificial replacement
target. This drill proves queue/review persistence, never OCR engine accuracy.
"""
import copy
import json
import os
from pathlib import Path
import re

if (os.environ.get('PAPERASSIST_ENV') != 'test'
        or os.environ.get('PAPERASSIST_QUEUE_TEST_ALLOWED') != '1'
        or not re.fullmatch(r'pa_test_[0-9a-f]{32}', os.environ.get('PAPERASSIST_DB_SCHEMA', ''))):
    raise SystemExit('OCR review queue drill requires an isolated UUID test schema.')

import httpx2
from app.adapters import ocr_process
from app.domain.documents.ocr_contracts import OcrParseResult
from ocr_samples import ocr_result

ROOT = Path('/data')
client_init = httpx2.Client.__init__
async_client_init = httpx2.AsyncClient.__init__


def reject_network(request):
    with (ROOT / '.unexpected-ocr-review-network').open('a', encoding='ascii') as stream:
        stream.write(request.method + '\n')
    raise AssertionError('OCR review must never contact an external model provider.')


def isolated_client(self, *args, **kwargs):
    kwargs['transport'] = httpx2.MockTransport(reject_network)
    return client_init(self, *args, **kwargs)


def isolated_async_client(self, *args, **kwargs):
    kwargs['transport'] = httpx2.MockTransport(reject_network)
    return async_client_init(self, *args, **kwargs)


def synthetic_ocr(content, filename, file_type, page_numbers, settings, *, on_started=None):
    result = ocr_result(content, filename, file_type, page_numbers, settings,
                        on_started=on_started).model_dump()
    for page in result['document']['pages']:
        original = page['text_blocks'][0]
        page['text_blocks'] = [copy.deepcopy(original) for _ in range(3)]
        for ordinal, block in enumerate(page['text_blocks']):
            block['id'] = f"text-{page['page_number']}-{ordinal + 1}"
            block['text'] = ['原文 12 mg', '测试夹具错字 12 rng', '模糊的合成文字'][ordinal]
    result['document']['counts']['text_blocks'] = 3 * len(page_numbers)
    with (ROOT / '.ocr-review-fixture-calls').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'filename': filename, 'page_numbers': page_numbers}) + '\n')
    return OcrParseResult.model_validate(result)


httpx2.Client.__init__ = isolated_client
httpx2.AsyncClient.__init__ = isolated_async_client
ocr_process.parse_ocr_isolated = synthetic_ocr

from app.workers.__main__ import main

if __name__ == '__main__':
    raise SystemExit(main())
