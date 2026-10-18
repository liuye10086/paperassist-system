from tests.helpers.projection import check_projection,confirm_projection
"""Contract evolution preserves historical inputs and never rewrites them on read."""
from copy import deepcopy
import pytest
from psycopg.types.json import Jsonb
from tests.api.test_analysis import client
from tests.integration.test_batch05_figure_store import source
from app.db.database import database_connection
from app.domain.external_processing import digest
from app.domain.figure_workbench.contracts import SaveConfiguration, ConfirmProjection
from app.domain.figure_workbench.sources import calculate, load_source
from app.core.exceptions import StorageError


@pytest.mark.parametrize('historical_contract', [1,2])
def test_new_contract_marker_preserves_exact_legacy_material_when_absent(client,historical_contract):
    workbench, project, result = source(client)
    args = (project, result['file_id'], result['id'])
    request = SaveConfiguration(config={'figure_kind':'bar','language':'en','projection':{'category_column':'C','bar_stat':'count'}})
    saved = workbench.save(*args, request); vid = saved['version']['id']
    with database_connection() as db:
        row = dict(db.execute('SELECT * FROM figure_config_versions WHERE id=%s',(vid,)).fetchone())
    assert row['source_json']['figure_contract'] == 3
    checked=check_projection(workbench,*args,vid)
    confirm_projection(workbench,*args,vid,ConfirmProjection(input_sha256=checked['input_sha256'],approved=True))
    new = workbench.material(*args, vid)
    assert new[3]['labels']['y_label'] and new[3]['presentation']['schema_version'] == 2
    # Construct a genuine pre-upgrade immutable row before any decision or task.
    legacy_saved=workbench.save(*args,request);vid=legacy_saved['version']['id']
    with database_connection() as db:row=dict(db.execute('SELECT * FROM figure_config_versions WHERE id=%s',(vid,)).fetchone())
    old_source = {k:v for k,v in row['source_json'].items() if k != 'figure_contract'}
    if historical_contract==2:old_source['figure_contract']=2
    old_hash = digest({'config':row['config_json'],'source':old_source})
    with database_connection(write=True) as db:
        db.execute('UPDATE figure_config_versions SET source_json=%s,sha256=%s WHERE id=%s',(Jsonb(old_source),old_hash,vid))
    checked=check_projection(workbench,*args,vid)
    confirm_projection(workbench,*args,vid,ConfirmProjection(input_sha256=checked['input_sha256'],approved=True))
    old = workbench.material(*args, vid)
    _, sheet = load_source(workbench.assets,*args)
    from app.domain.statistics_execution.verification import verification_scope
    with verification_scope():_, payload, expected = calculate(workbench.assets,project,result['file_id'],result,sheet,row['config_json'])
    if historical_contract==2:
        from app.domain.figure_workbench.presentation import enrich_material
        from app.domain.figure_workbench.sources import fields_for
        payload,expected=enrich_material(payload,expected,config=row['config_json'],result=result,projection=old[2],fields={f['column']:f for f in fields_for(sheet)})
    assert old[3] == payload and old[4] == expected
    assert ('presentation' in old[3]) == (historical_contract==2)
    checked=check_projection(workbench,*args,vid)
    confirm_projection(workbench,*args,vid,ConfirmProjection(input_sha256=checked['input_sha256'],approved=True))
    second=workbench.save(*args,SaveConfiguration(configuration_id=legacy_saved['id'],expected_revision=1,config=request.config))
    assert second['version']['figure_contract']==3
    assert second['projection'] is None  # Changing the contract needs a fresh projection confirmation.
    with database_connection() as db:
        retained=dict(db.execute('SELECT * FROM figure_config_versions WHERE id=%s',(vid,)).fetchone())
    assert retained['source_json'] == old_source and retained['sha256'] == old_hash


def test_unknown_contract_rejected_even_with_recomputed_hash(client):
    workbench,project,result=source(client);args=(project,result['file_id'],result['id'])
    saved=workbench.save(*args,SaveConfiguration(config={'figure_kind':'line','language':'en','projection':{'x_column':'A','y_column':'C'}}))
    vid=saved['version']['id']
    with database_connection(write=True) as db:
        row=db.execute('SELECT * FROM figure_config_versions WHERE id=%s',(vid,)).fetchone()
        changed=deepcopy(row['source_json']);changed['figure_contract']=99
        db.execute('UPDATE figure_config_versions SET source_json=%s,sha256=%s WHERE id=%s',(Jsonb(changed),digest({'config':row['config_json'],'source':changed}),vid))
    with pytest.raises(StorageError):workbench.material(*args,vid)


def test_missing_sd_is_readable_in_confirmation_without_changing_numeric_projection(client):
    workbench,project,result=source(client);args=(project,result['file_id'],result['id'])
    saved=workbench.save(*args,SaveConfiguration(config={'figure_kind':'bar','language':'en','projection':{'category_column':'A','y_column':'C','bar_stat':'mean','error_bars':'sd'}}))
    checked=check_projection(workbench,*args,saved['version']['id'])
    assert len(checked['diagnostics']) == 4
    assert all('SD' in item['reason'] and '2' in item['reason'] for item in checked['diagnostics'])
    assert all(set(item)=={'label','reason'} and item['label'] for item in checked['diagnostics'])
    confirm_projection(workbench,*args,saved['version']['id'],ConfirmProjection(input_sha256=checked['input_sha256'],approved=True))
    material=workbench.material(*args,saved['version']['id'])
    assert all(p['sd'] is None and p['reason']=='insufficient_n_for_sd' for p in material[2]['series'][0]['points'])
