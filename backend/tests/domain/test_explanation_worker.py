"""The durable transport entry point delegates both task types by database identity."""


def test_existing_durable_message_name_uses_unified_executor(monkeypatch):
    from app.domain.tasks import execution
    from app.workers.celery_app import create_app
    monkeypatch.setenv('PAPERASSIST_BROKER_URL', 'amqp://worker:private@broker:5672/test')
    monkeypatch.setenv('PAPERASSIST_TASK_QUEUE', 'paperassist.test.fixture')
    monkeypatch.setenv('PAPERASSIST_QUEUE_TEST_ALLOWED', '1')
    calls = []
    monkeypatch.setattr(execution, 'run_task', lambda *args: calls.append(args))
    app = create_app()
    app.tasks['paperassist.word_report'].run('explanation-task', 7)
    assert calls == [('explanation-task', 7)]
