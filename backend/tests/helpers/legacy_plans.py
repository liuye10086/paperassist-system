"""Seed historical v1-v4 plans for retention/regression fixtures only.

New HTTP clients must use v5. These tests intentionally reproduce a stored old
workflow through its unchanged domain builder, then use real workers and APIs
to verify continuation/read compatibility. No production guard is disabled.
"""
import re

import json as jsonlib
from requests import Response
from fastapi import HTTPException
from pydantic import ValidationError


def seed_legacy_plan(client, url, *, json, headers=None, **kwargs):
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
    from app.domain.analysis_plan.service import AnalysisPlanService
    from app.domain.analysis_plan.contracts import AnalysisPlanCreateRequest
    from app.domain.analysis_plan.requirements import RequirementCreateRequest
    from app.domain.analysis_plan.requirements_service import create_requirement
    store = ProjectStore(get_data_dir(), owner_id=me.json()['user']['id'])
    parts = url.split('/'); project = parts[4]
    key = next((value for name, value in (headers or {}).items() if name.lower() == 'idempotency-key'), None)
    try:
        if json.get('schema_version') == 4:
            request = RequirementCreateRequest.model_validate(json)
            value, status = create_requirement(AnalysisPlanService(store), project, request, key)
        else:
            request = AnalysisPlanCreateRequest.model_validate(json)
            value, status = AnalysisPlanService(store).create(project, parts[6], request, key)
    except StorageError as exc:
        value, status = {'detail': {'code': exc.code, 'message': exc.message}}, exc.status
    except HTTPException as exc:
        value, status = {'detail': exc.detail}, exc.status_code
    except ValidationError:
        value, status = {'detail': 'Historical plan fixture is invalid.'}, 422
    response = Response(); response.status_code = status
    response._content = jsonlib.dumps(value).encode('utf-8')
    response.headers['Content-Type'] = 'application/json'
    return response
