"""The new school flow uses the same backend-owned submission evidence."""
from copy import deepcopy

import pytest

from tests.domain.test_model_usage_provenance import module, request, subject, task


@pytest.fixture(autouse=True)
def postgres_schema():
    yield None


@pytest.mark.parametrize('workflow,expected', [
    ('school_rule_suggestion_v1', 'openai_live'),
    ('school_rule_suggestion_v2', None),
    ('explanation_v1', None),
])
def test_school_advice_labels_only_the_registered_backend_flow(workflow, expected):
    from app.adapters.models.openai_responses import OpenAIResponsesProvider
    p = module()
    provider = OpenAIResponsesProvider(api_key='offline-test-only')
    call = subject(task_type='school_rule_suggestion', workflow_version=workflow)
    before = deepcopy(call)
    try:
        context = p.admission_context(provider, request=request(), operation='text')
        state = p.apply_admission_provenance(call, task(task_type='school_rule_suggestion', workflow_version=workflow), context)
    finally:
        provider.close()
    assert p.public_provider_provenance({**call, 'provider_state': state}) == expected
    assert call == before
    assert p.public_provider_provenance(call) is None
