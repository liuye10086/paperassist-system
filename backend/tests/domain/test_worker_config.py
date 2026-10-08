import pytest


def test_worker_explicit_secret_allowlist_and_no_model_secrets(monkeypatch, tmp_path):
    from app.workers.config import load_secrets
    secret = tmp_path / 'broker'
    secret.write_text('amqp://worker:private@broker:5672/paperassist\n', encoding='utf-8')
    monkeypatch.setenv('PAPERASSIST_BROKER_URL', '')
    monkeypatch.setenv('PAPERASSIST_BROKER_URL_FILE', str(secret))
    monkeypatch.setenv('OPENAI_API_KEY_FILE', str(secret))
    load_secrets()
    import os
    assert os.environ['PAPERASSIST_BROKER_URL'] == 'amqp://worker:private@broker:5672/paperassist'
    assert os.environ['OPENAI_API_KEY'] == ''


def test_queue_config_rejects_implicit_development_queue_in_test(monkeypatch):
    from app.workers.config import queue_config
    monkeypatch.setenv('PAPERASSIST_BROKER_URL', 'amqp://worker:private@broker:5672/paperassist')
    monkeypatch.delenv('PAPERASSIST_TASK_QUEUE', raising=False)
    monkeypatch.delenv('PAPERASSIST_QUEUE_TEST_ALLOWED', raising=False)
    with pytest.raises(ValueError):
        queue_config()


def test_celery_configuration_is_durable_confirmed_and_json_only(monkeypatch):
    from app.workers.celery_app import create_app
    monkeypatch.setenv('PAPERASSIST_BROKER_URL', 'amqp://worker:private@broker:5672/test')
    monkeypatch.setenv('PAPERASSIST_TASK_QUEUE', 'paperassist.test.fixture')
    monkeypatch.setenv('PAPERASSIST_QUEUE_TEST_ALLOWED', '1')
    app = create_app()
    assert app.conf.broker_transport_options['confirm_publish']
    assert app.conf.accept_content == ['json']
    assert app.conf.result_backend is None and app.conf.task_ignore_result
    assert app.conf.task_acks_late and app.conf.task_reject_on_worker_lost
    assert app.conf.task_queues[0].durable
    assert app.conf.task_default_delivery_mode == 'persistent'
    # RabbitMQ 4.3 rejects non-durable, non-exclusive auxiliary queues.
    assert app.control.mailbox.get_queue('test-worker').exclusive
    assert app.control.mailbox.get_reply_queue().exclusive
    assert app.conf.event_queue_exclusive


def test_publish_uses_identifiers_and_confirm_timeout(monkeypatch):
    from app.workers import celery_app
    monkeypatch.setenv('PAPERASSIST_BROKER_URL', 'amqp://worker:private@broker:5672/test')
    monkeypatch.setenv('PAPERASSIST_TASK_QUEUE', 'paperassist.test.fixture')
    monkeypatch.setenv('PAPERASSIST_QUEUE_TEST_ALLOWED', '1')
    app = celery_app.create_app()
    sent = []
    monkeypatch.setattr(app, 'send_task', lambda *args, **kwargs: sent.append((args, kwargs)))
    celery_app.publish_confirmed({'id': 'event', 'task_id': 'task', 'task_revision': 1}, app=app)
    name, options = sent[0]
    assert name == ('paperassist.word_report',)
    assert options['args'] == ['task', 1] and options['task_id'] == 'event'
    assert options['confirm_timeout'] == 5 and options['retry'] is False


def test_dispatcher_health_rejects_old_or_missing_timestamp(monkeypatch, tmp_path):
    from app.workers.__main__ import dispatch_health
    import time
    path = tmp_path / 'health'
    monkeypatch.setenv('PAPERASSIST_WORKER_HEALTH_FILE', str(path))
    assert not dispatch_health()
    path.write_text(str(time.time()), encoding='ascii')
    assert dispatch_health()
    path.write_text(str(time.time() - 46), encoding='ascii')
    assert not dispatch_health()


def test_worker_cli_health_rejects_stale_database_before_broker_contact(monkeypatch, capsys):
    from app.workers.__main__ import main
    from app.db import database
    monkeypatch.setenv('PAPERASSIST_BROKER_URL', 'amqp://worker:private@broker:5672/test')
    monkeypatch.setenv('PAPERASSIST_TASK_QUEUE', 'paperassist.test.fixture')
    monkeypatch.setenv('PAPERASSIST_QUEUE_TEST_ALLOWED', '1')
    def stale(_):
        raise database.SchemaVersionError('private diagnostic')
    monkeypatch.setattr(database, 'ensure_schema_current', stale)
    assert main(['health', 'worker']) == 1
    assert 'private diagnostic' not in capsys.readouterr().err
