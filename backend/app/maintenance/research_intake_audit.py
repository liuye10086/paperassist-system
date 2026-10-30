"""Read-only scope/hash audits; contacts and research prose never enter output."""
import json
import sys
from app.domain.research_intake.contracts import RequirementContent, DesignContent
from app.domain.research_intake.service import digest


def audit_research_intakes(db,limit=200):
    if type(limit) is not int or not 1<=limit<=1000:
        raise ValueError('Invalid audit limit')
    checks=[]
    roots=db.execute('SELECT * FROM research_intakes ORDER BY project_id LIMIT %s',(limit,)).fetchall()
    invalid=0
    for row in roots:
        project=db.execute('SELECT owner_id,project_type FROM projects WHERE id=%s',(row['project_id'],)).fetchone()
        valid=bool(project and row['owner_id']==project['owner_id'])
        if project and project['project_type']=='research':
            valid &= bool(row['owner_id'] and row['creation_request_key'] and row['creation_digest'])
        for table,pointer in [('research_requirement_versions','current_requirement_version_id'),('research_design_versions','current_design_version_id')]:
            latest=db.execute(f'SELECT id FROM {table} WHERE project_id=%s ORDER BY version DESC LIMIT 1',(row['project_id'],)).fetchone()
            valid &= row[pointer]==(latest['id'] if latest else None)
        invalid+=not valid
    total=db.execute('SELECT count(*) AS n FROM research_intakes').fetchone()['n']
    missing=db.execute('SELECT count(*) AS n FROM projects p LEFT JOIN research_intakes i ON i.project_id=p.id WHERE i.project_id IS NULL').fetchone()['n']
    checks.append(dict(table='research_intakes',column='owner_current_versions',rows=len(roots),total=total,truncated=total>len(roots),invalid=invalid+missing))
    for table,model in [('research_requirement_versions',RequirementContent),('research_design_versions',DesignContent)]:
        rows=db.execute(f'SELECT * FROM {table} ORDER BY project_id,version LIMIT %s',(limit,)).fetchall();invalid=0
        for row in rows:
            try:
                value=model.model_validate(row['content_json']).model_dump(mode='json')
                project=db.execute('SELECT owner_id FROM projects WHERE id=%s',(row['project_id'],)).fetchone()
                parent=db.execute(f'SELECT id FROM {table} WHERE project_id=%s AND version=%s',(row['project_id'],row['version']-1)).fetchone()
                if (value!=row['content_json'] or digest(value)!=row['sha256'] or not project or project['owner_id']!=row['created_by']
                        or row['parent_id']!=(parent['id'] if parent else None)):
                    raise ValueError('Version identity differs')
                if row['version']>1 and parent is None:
                    raise ValueError('Version sequence gap')
            except Exception:
                invalid+=1
        total=db.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n']
        checks.append(dict(table=table,column='immutable_content_parent_owner',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid))
    rows=db.execute('SELECT * FROM research_material_refs ORDER BY id LIMIT %s',(limit,)).fetchall();invalid=0
    for row in rows:
        version_table,column=('research_requirement_versions','requirement_version_id') if row['requirement_version_id'] else ('research_design_versions','design_version_id')
        valid=bool(db.execute(f'SELECT id FROM {version_table} WHERE id=%s AND project_id=%s',(row[column],row['project_id'])).fetchone())
        for table,key in [('files','file_id'),('bio_dataset_versions','bio_dataset_version_id'),('research_deliveries','delivery_id')]:
            if row[key]:
                valid &= bool(db.execute(f'SELECT id FROM {table} WHERE id=%s AND project_id=%s',(row[key],row['project_id'])).fetchone())
        invalid+=not valid
    total=db.execute('SELECT count(*) AS n FROM research_material_refs').fetchone()['n']
    checks.append(dict(table='research_material_refs',column='scoped_actual_objects',rows=len(rows),total=total,truncated=total>len(rows),invalid=invalid))
    return checks


def main():
    from app.db.database import database_connection
    try:
        with database_connection() as db:
            checks=audit_research_intakes(db)
        result={'ok':not any(x['invalid'] for x in checks),'data_checks':checks,'read_only':True}
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['ok'] else 1
    except Exception:
        print('研究需求审计失败，请检查数据库结构和权限。',file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
