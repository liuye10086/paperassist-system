"""The default test environment cannot inherit the developer's real model key."""

from app.core.config import local_config


def test_default_test_environment_has_no_model_key():
    has_key = bool(local_config().get('OPENAI_API_KEY'))
    assert not has_key
