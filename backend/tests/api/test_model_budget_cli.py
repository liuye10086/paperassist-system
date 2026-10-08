"""Trusted local administration validates exact money and never invents a budget."""
import json

import pytest

from app.db.database import database_connection
from tests.db.test_task_schema import seed_owner


@pytest.mark.parametrize('text,expected', [('0', 0), ('2.05', 2_050_000), ('0.000001', 1), ('1000000', 1_000_000_000_000)])
def test_money_is_exact_decimal_micro_usd(text, expected):
    from app.manage_model_budgets import parse_usd
    assert parse_usd(text) == expected


@pytest.mark.parametrize('text', ['NaN', 'Infinity', '1e3', '-1', '0.0000001', '1000000.000001', ' 2', '.5', ''])
def test_invalid_or_inexact_money_is_rejected(text):
    from app.manage_model_budgets import parse_usd
    with pytest.raises(ValueError):
        parse_usd(text)


def test_show_does_not_create_budget_and_set_requires_revision(postgres_schema, capsys):
    from app.manage_model_budgets import main
    with database_connection(write=True) as db:
        seed_owner(db)
    common = ['--user-email', 'u@example.invalid', '--scope', 'user']
    assert main(['show', *common]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['limit_micro_usd'] is None and result['revision'] == 0
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_budgets').fetchone()['n'] == 0
    assert main(['set', *common, '--limit-usd', '2.05', '--expected-revision', '0']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['limit_micro_usd'] == 2_050_000 and result['revision'] == 1
    assert main(['set', *common, '--limit-usd', '3', '--expected-revision', '0']) == 1
    assert 'model_budget_revision_conflict' in capsys.readouterr().err
    with database_connection() as db:
        row = db.execute('SELECT limit_micro_usd,revision FROM model_budgets').fetchone()
        assert row['limit_micro_usd'] == 2_050_000 and row['revision'] == 1


def test_set_rejects_project_outside_target_user(postgres_schema, capsys):
    from app.manage_model_budgets import main
    with database_connection(write=True) as db:
        seed_owner(db)
    assert main(['set', '--user-email', 'u@example.invalid', '--scope', 'project', '--scope-id', 'missing',
                 '--limit-usd', '2', '--expected-revision', '0']) == 1
    assert 'project_not_found' in capsys.readouterr().err
    with database_connection() as db:
        assert db.execute('SELECT count(*) AS n FROM model_budgets').fetchone()['n'] == 0


def test_cli_does_not_print_connection_failure_secrets(monkeypatch, capsys):
    from app import manage_model_budgets as command
    monkeypatch.setattr(command, 'get_database_config', lambda: (_ for _ in ()).throw(ValueError('secret-password')))
    assert command.main(['show', '--user-email', 'u@example.invalid', '--scope', 'user']) == 1
    output = capsys.readouterr()
    assert 'secret-password' not in output.err and not output.out


@pytest.mark.parametrize('arguments', [
    ['set'],
    ['show', '--limit-usd', '1'],
    ['set', '--scope-id', 'someone-else', '--limit-usd', '1', '--expected-revision', '0'],
])
def test_cli_rejects_ambiguous_write_or_user_scope_arguments(arguments):
    from app.manage_model_budgets import main
    with pytest.raises(SystemExit) as raised:
        main([*arguments, '--user-email', 'u@example.invalid', '--scope', 'user'])
    assert raised.value.code == 2
