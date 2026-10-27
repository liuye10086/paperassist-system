"""Read-only versioned policy seam; update dates come from saved versions."""


def source_directory():
    return [dict(id=kind,version='local-journal-sources-v1',mode='local_only',update_mode='manual',
        require_verification=True,requires_located_quote=True,permission_verification='owner_record_required',
        real_connectivity='not_tested',official_verification='not_established',verified_on=None,
        verification_scope='synthetic_material_only' if kind=='synthetic' else 'local_source_record_only')
        for kind in ('official_local','open_local','user_provided','synthetic')]


def configuration(db,project,user):
    from app.domain.admin_configuration.bindings import resolve
    from app.domain.admin_configuration.rule_consumption import rules
    version=resolve(db);policy=rules(version,'journals')
    dates={}
    for kind,table in [('profile','journal_profiles'),('guide','journal_guides')]:
        row=db.execute("SELECT max(snapshot_json->>'verified_on') AS date FROM "+table+' WHERE project_id=%s AND user_id=%s',(project,user)).fetchone()
        dates['latest_'+kind+'_verified_on']=row['date']
    return dict(source_policy=dict(version=1,mode=policy['source_mode'],metrics_enabled=policy['metrics_enabled'],
        require_verification=policy['require_verification'],source_label=policy['source_label']),
        recommendation_policy=dict(version=policy['recommendation_version'],default_count=policy['default_count'],max_count=policy['max_count']),
        default_limit=policy['default_count'],max_limit=policy['max_count'],metrics_enabled=policy['metrics_enabled'],
        source_directory=source_directory(),
        format_version=policy['format_version'],updates=dates|{key:policy[key] for key in ('update_mode','update_plan','update_result','update_note')},
        configuration=dict(status='bound' if version else 'legacy_unbound',version_id=version['id'] if version else None,sha256=version['sha256'] if version else None))
