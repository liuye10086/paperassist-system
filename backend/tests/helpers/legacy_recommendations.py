"""Explicit historical recommendation seeds; new HTTP intake remains v5-only.

Only isolated TEST schemas may use the unchanged domain preview/create builder
to reconstruct old persisted work before exercising real recovery/read paths.
"""
import re

import json as jsonlib
from requests import Response
from fastapi import HTTPException
from pydantic import ValidationError


def seed_legacy_recommendation(client, url, *, json, headers=None, **kwargs):
    if json.get('schema_version') == 5:
        return client.post(url, json=json, headers=headers, **kwargs)
    from app.db.database import get_database_config
    config = get_database_config()
    assert config.environment == 'test' and config.url.database == 'paperassist_system_test'
    assert re.fullmatch(r'pa_test_[0-9a-f]{32}', config.schema)
    me = client.get('/api/v1/auth/me')
    if me.status_code != 200:
        return client.post(url, json=json, headers=headers, **kwargs)
    from app.adapters.storage import ProjectStore
    from app.core.config import get_data_dir
    from app.core.exceptions import StorageError
    from app.domain.analysis_recommendation.service import RecommendationService
    from app.domain.analysis_recommendation.contracts import parse_request
    store = ProjectStore(get_data_dir(), owner_id=me.json()['user']['id'])
    parts = url.split('/')
    assert len(parts) in (8, 9) and parts[3] == 'projects' and parts[5] == 'files'
    assert parts[7] == 'analysis-recommendations'
    preview = len(parts) == 9
    assert not preview or parts[8] == 'preview'
    key = next((value for name, value in (headers or {}).items() if name.lower() == 'idempotency-key'), None)
    try:
        request = parse_request(json, create=not preview)
        service = RecommendationService(store)
        if preview:
            value, status = service.preview(parts[4], parts[6], request), 200
        else:
            value, status = service.create(parts[4], parts[6], request, key)
    except StorageError as exc:
        value, status = {'detail': {'code': exc.code, 'message': exc.message}}, exc.status
    except HTTPException as exc:
        value, status = {'detail': exc.detail}, exc.status_code
    except ValidationError:
        value, status = {'detail': 'Historical recommendation fixture is invalid.'}, 422
    response = Response()
    response.status_code = status
    response._content = jsonlib.dumps(value).encode('utf-8')
    response.headers['Content-Type'] = 'application/json'
    return response
