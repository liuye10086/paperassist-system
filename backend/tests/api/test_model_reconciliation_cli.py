"""Local evidence handling uses exact money and never prints sensitive input."""
import getpass
import hashlib
import json
import pytest

from app.core.exceptions import StorageError
from app.db.database import database_connection
from tests.integration.test_model_usage import context, call, response
from tests.integration.test_model_reconciliation import plot


def record_file(tmp_path, **changes):
    evidence = tmp_path / 'provider-evidence.txt'
    if not evidence.exists():
        evidence.write_bytes(b'SYNTHETIC-EVIDENCE-SECRET')
    data = dict(event_key='actual-token-1', expected_revision=0, component='token',
        amount_usd='0.000050', evidence_kind='provider_statement',
        evidence_reference='statement:synthetic-item', provider_object_id='response-test',
        evidence_file=evidence.name)
    data.update(changes)
    record = tmp_path / 'record.json'
    record.write_text(json.dumps(data), encoding='utf-8')
    return record


def arguments(command, record=None, call_id='call-test', email='model-test@local.test'):
    values = [command, '--user-email', email, '--call-id', call_id]
    return [*values, '--record-file', str(record)] if record else values


@pytest.mark.parametrize('value,expected', [
    ('0', 0), ('0.000001', 1), ('2.05', 2_050_000),
    ('1000000.000001', 1_000_000_000_001),
    ('9223372036854.775807', 2**63 - 1), ('0002.050000', 2_050_000),
])
def test_amount_is_exact_and_uses_storage_limit(value, expected):
    from app.manage_model_reconciliation import parse_usd
    assert parse_usd(value) == expected


@pytest.mark.parametrize('value', [
    '9223372036854.775808', '1e3', '-0', '-1', 'NaN', 'Infinity',
    '0.0000001', ' 2', '2 ', '.5', '1.', '', 1, 0.1, True,
])
def test_invalid_inexact_or_overflow_amount_is_rejected(value):
    from app.manage_model_reconciliation import parse_usd
    with pytest.raises(ValueError):
        parse_usd(value)


def test_load_computes_original_bytes_hash_and_local_operator(tmp_path, monkeypatch):
    from app.manage_model_reconciliation import load_record
    monkeypatch.setattr(getpass, 'getuser', lambda: 'local-admin')
    record = record_file(tmp_path)
    loaded = load_record(record)
    assert loaded.amount_micro_usd == 50
    assert loaded.operator == 'local-admin'
    assert loaded.evidence_sha256 == hashlib.sha256(b'SYNTHETIC-EVIDENCE-SECRET').hexdigest()
    assert 'evidence_file' not in loaded.model_dump()
    assert str(tmp_path) not in json.dumps(loaded.model_dump())
    (tmp_path / 'provider-evidence.txt').write_bytes(b'CHANGED-SYNTHETIC-ORIGINAL')
    assert load_record(record).evidence_sha256 != loaded.evidence_sha256


@pytest.mark.parametrize('changes', [
    {'operator': 'untrusted-admin'}, {'amount_micro_usd': 50}, {'currency': 'USD'},
    {'evidence_file': 'missing.txt'}, {'evidence_file': '../outside.txt'},
    {'evidence_file': 'https://example.invalid/evidence'},
    {'evidence_file': r'\\server\share\secret.txt'},
    {'evidence_file': r'C:\secret.txt'}, {'evidence_file': 2},
    {'expected_revision': True}, {'expected_revision': 0.5},
    {'amount_usd': 0.000050}, {'evidence_reference': 'bad\nreference'},
    {'evidence_reference': 'bad\u202ereference'},
])
def test_record_rejects_untrusted_fields_paths_and_contract_values(tmp_path, changes):
    from app.manage_model_reconciliation import load_record
    with pytest.raises((ValueError, OSError)):
        load_record(record_file(tmp_path, **changes))


@pytest.mark.parametrize('content', [
    b'{"event_key":"one","event_key":"two"}', b'[]', b'{}', b'\xff',
])
def test_record_rejects_duplicate_missing_nonobject_or_non_utf8_json(tmp_path, content):
    from app.manage_model_reconciliation import load_record
    record = tmp_path / 'record.json'
    record.write_bytes(content)
    with pytest.raises(ValueError):
        load_record(record)


def test_existing_file_outside_record_directory_is_rejected(tmp_path):
    from app.manage_model_reconciliation import load_record
    (tmp_path.parent / 'outside.txt').write_bytes(b'OUTSIDE-PRIVATE-EVIDENCE')
    with pytest.raises(ValueError):
        load_record(record_file(tmp_path, evidence_file='../outside.txt'))


def test_empty_evidence_is_not_a_provider_original(tmp_path):
    from app.manage_model_reconciliation import load_record
    record = record_file(tmp_path)
    (tmp_path / 'provider-evidence.txt').write_bytes(b'')
    with pytest.raises(ValueError):
        load_record(record)


def test_show_output_whitelists_provider_and_audit_metadata():
    from app.manage_model_reconciliation import _show_result
    raw = dict(call_id='call-test', status='completed',
        policy_snapshot={'secret': 'SECRET-POLICY'},
        provider_state={'container_id': 'cntr_test', 'secret': 'SECRET-PROVIDER'},
        history=[{'event_key': 'proof', 'created_at': None, 'secret': 'SECRET-EVENT',
            'reconciliation': {'revision': 1, 'request': {'operator': 'local-admin',
                'evidence_file': 'SECRET-PATH', 'evidence_content': 'SECRET-ORIGINAL'},
                'receipt': {'actual_micro_usd': 50, 'secret': 'SECRET-RECEIPT'},
                'secret': 'SECRET-PAYLOAD'}}])
    shown = _show_result(raw)
    assert 'SECRET' not in json.dumps(shown)
    assert shown['container_id'] == 'cntr_test'
    assert shown['history'][0]['reconciliation']['request']['operator'] == 'local-admin'


@pytest.mark.parametrize('argv', [
    ['show', '--record-file', r'C:\secret-path'], ['preview'], ['apply'],
    ['show', '--operator', 'secret-admin'], ['secret-command'],
])
def test_argument_errors_never_echo_user_input(argv, capsys):
    from app.manage_model_reconciliation import main
    with pytest.raises(SystemExit) as raised:
        main([*argv, '--user-email', 'u@example.invalid', '--call-id', 'call-test'])
    assert raised.value.code == 2
    output = capsys.readouterr()
    assert not output.out
    assert 'secret-' not in output.err


@pytest.mark.parametrize('error', [
    ValueError('password=SECRET-CONNECTION'),
    StorageError('unsafe-secret-code', 'SECRET-EVIDENCE-CONTENT'),
    StorageError('model_reconciliation_revision_conflict', 'SECRET-EVIDENCE-CONTENT'),
])
def test_failures_do_not_print_secrets_database_or_paths(monkeypatch, capsys, error):
    from app import manage_model_reconciliation as command
    def failing():
        raise error
    monkeypatch.setattr(command, 'get_database_config', failing)
    assert command.main(arguments('show')) == 1
    output = capsys.readouterr()
    assert not output.out
    assert 'SECRET' not in output.err and 'unsafe-secret' not in output.err
    if isinstance(error, StorageError) and error.code == 'model_reconciliation_revision_conflict':
        assert error.code in output.err


def snapshot():
    with database_connection() as db:
        return {
            table: db.execute(f'SELECT * FROM {table} ORDER BY 1,2').fetchall()
            for table in ('model_calls', 'usage_events', 'budget_reservations', 'tasks')
        }


def test_preview_is_read_only_apply_replays_and_operator_is_recorded(context, tmp_path, monkeypatch, capsys):
    from app.manage_model_reconciliation import main
    monkeypatch.setattr(getpass, 'getuser', lambda: 'cli-test-admin')
    service, saved = call(context)
    response(service, saved)
    before = snapshot()
    record = record_file(tmp_path)
    assert main(arguments('preview', record, saved['id'])) == 0
    preview = json.loads(capsys.readouterr().out)
    assert preview['actual_micro_usd'] == 50 and preview['delta_micro_usd'] == -10
    assert snapshot() == before
    assert main(arguments('apply', record, saved['id'])) == 0
    applied = json.loads(capsys.readouterr().out)
    assert applied == preview
    after = snapshot()
    assert main(arguments('apply', record, saved['id'])) == 0
    assert json.loads(capsys.readouterr().out) == applied
    assert snapshot() == after
    with database_connection() as db:
        payload = db.execute("SELECT reconciliation FROM usage_events WHERE event_type='reconciliation'").fetchone()['reconciliation']
    assert 'cli-test-admin' in json.dumps(payload)
    assert 'SYNTHETIC-EVIDENCE-SECRET' not in json.dumps(payload)
    assert str(tmp_path) not in json.dumps(payload)
    assert main(arguments('show', call_id=saved['id'])) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown['call_id'] == saved['id']
    assert snapshot() == after


@pytest.mark.parametrize('changes', [
    {'provider_object_id': 'wrong-response'}, {'expected_revision': 1},
])
def test_wrong_association_or_revision_is_rejected_without_write(context, tmp_path, changes, capsys):
    from app.manage_model_reconciliation import main
    service, saved = call(context)
    response(service, saved)
    before = snapshot()
    assert main(arguments('apply', record_file(tmp_path, **changes), saved['id'])) == 1
    assert not capsys.readouterr().out
    assert snapshot() == before


def test_original_bytes_change_conflicts_on_replay(context, tmp_path, capsys):
    from app.manage_model_reconciliation import main
    service, saved = call(context)
    response(service, saved)
    record = record_file(tmp_path)
    assert main(arguments('apply', record, saved['id'])) == 0
    capsys.readouterr()
    before = snapshot()
    (tmp_path / 'provider-evidence.txt').write_bytes(b'DIFFERENT-SYNTHETIC-EVIDENCE')
    assert main(arguments('apply', record, saved['id'])) == 1
    output = capsys.readouterr()
    assert not output.out and 'DIFFERENT-SYNTHETIC' not in output.err
    assert snapshot() == before


def test_missing_evidence_does_not_print_paths_or_write(context, tmp_path, capsys):
    from app.manage_model_reconciliation import main
    service, saved = call(context)
    response(service, saved)
    before = snapshot()
    record = record_file(tmp_path, evidence_file='missing-sensitive-original.txt')
    assert main(arguments('apply', record, saved['id'])) == 1
    output = capsys.readouterr()
    assert not output.out
    assert 'missing-sensitive' not in output.err and str(tmp_path) not in output.err
    assert snapshot() == before


def test_tool_partial_full_and_negative_correction_via_cli(context, tmp_path, capsys):
    from app.manage_model_reconciliation import main
    service, saved = plot(context)
    tool_record = record_file(tmp_path, event_key='tool-proof', component='tool',
        provider_object_id='cntr_test', amount_usd='0.000600')
    assert main(arguments('apply', tool_record, saved['id'])) == 0
    partial = json.loads(capsys.readouterr().out)
    assert partial['reconciliation_status'] == 'partial'
    assert partial['reserved_after_micro_usd'] == 600
    token_record = record_file(tmp_path, event_key='token-proof', expected_revision=1,
        amount_usd='0.001000')
    assert main(arguments('apply', token_record, saved['id'])) == 0
    complete = json.loads(capsys.readouterr().out)
    assert complete['reconciliation_status'] == 'reconciled'
    assert complete['accounted_after_micro_usd'] == 1600 and complete['reserved_after_micro_usd'] == 0
    correction = record_file(tmp_path, event_key='token-correction', expected_revision=2,
        amount_usd='0.000900')
    assert main(arguments('apply', correction, saved['id'])) == 0
    corrected = json.loads(capsys.readouterr().out)
    assert corrected['delta_micro_usd'] == -100
    assert corrected['accounted_after_micro_usd'] == 1500
    assert service.get_call(saved['id'])['estimated_cost_micro_usd'] == 1010


def test_cli_denies_other_account_and_missing_active_user(context, tmp_path, capsys):
    from app.auth.service import create_user
    from app.manage_model_reconciliation import main
    service, saved = call(context)
    response(service, saved)
    create_user('other-cli@local.test', 'safe-test-password-2026')
    before = snapshot()
    record = record_file(tmp_path)
    assert main(arguments('apply', record, saved['id'], 'other-cli@local.test')) == 1
    assert 'model_call_not_found' in capsys.readouterr().err
    assert main(arguments('show', call_id=saved['id'], email='absent-cli@local.test')) == 1
    assert not capsys.readouterr().out
    assert snapshot() == before
