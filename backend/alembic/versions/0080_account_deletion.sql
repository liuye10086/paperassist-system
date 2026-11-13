CREATE FUNCTION __APP_SCHEMA__.erase_account_records(
    operator_id text, target_id text, expected_revision integer, asset_plan jsonb
) RETURNS text
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, __APP_SCHEMA__, pg_temp
AS $$
DECLARE
    target users%ROWTYPE;
    owned_projects text[];
    anonymous_id constant text := 'deleted-account';
    app_namespace oid := (SELECT relnamespace FROM pg_class WHERE oid = 'users'::regclass);
    edge record;
    seal record;
    attribution record;
    retained_attribution boolean;
    generation integer := 0;
    delete_queries text;
    request_key_sql text;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM users WHERE id = operator_id AND role = 'admin' AND active) THEN
        RETURN 'permission_denied';
    END IF;
    SELECT * INTO target FROM users WHERE id = target_id FOR UPDATE;
    IF NOT FOUND OR target_id = anonymous_id THEN
        RETURN 'admin_user_not_found';
    END IF;
    IF target.role IS NULL OR target.role NOT IN ('customer', 'analyst') THEN
        RETURN 'account_delete_protected';
    END IF;
    IF target.admin_revision <> expected_revision THEN
        RETURN 'admin_revision_conflict';
    END IF;

    IF asset_plan IS NULL THEN
        DELETE FROM account_deletions WHERE user_id = target_id;
        IF NOT FOUND THEN
            RETURN 'account_delete_incomplete';
        END IF;
        DELETE FROM auth_login_attempts WHERE email = target.email;
        DELETE FROM users WHERE id = target_id;
        RETURN NULL;
    END IF;

    SELECT ARRAY(SELECT id FROM projects WHERE owner_id = target_id) INTO owned_projects;
    IF EXISTS (SELECT 1 FROM tasks WHERE project_id = ANY(owned_projects) AND status = 'running')
       OR EXISTS (SELECT 1 FROM model_calls WHERE project_id = ANY(owned_projects)
                  AND status IN ('reserved', 'submitting', 'submitted', 'submission_unknown'))
       OR EXISTS (SELECT 1 FROM bio_cloud_runs WHERE project_id = ANY(owned_projects)
                  AND status IN ('submitting', 'submission_unknown', 'pending', 'running', 'cancelling', 'collecting'))
       OR EXISTS (SELECT 1 FROM bio_cloud_uploads WHERE project_id = ANY(owned_projects)
                  AND status IN ('initializing', 'uploading', 'completing', 'cancelling', 'initialization_unknown')) THEN
        RETURN 'account_delete_blocked';
    END IF;

    -- The application holds the schema's write lock. Select exact rows, including
    -- descendants without a project_id, before deleting the complete FK graph.
    CREATE TEMP TABLE account_erase_rows (
        relation oid, row_tid tid, depth integer NOT NULL DEFAULT 0,
        PRIMARY KEY (relation, row_tid)
    ) ON COMMIT DROP;
    INSERT INTO pg_temp.account_erase_rows(relation, row_tid)
        SELECT 'projects'::regclass, ctid FROM projects WHERE id = ANY(owned_projects)
        UNION ALL SELECT 'sessions'::regclass, ctid FROM sessions WHERE user_id = target_id
        UNION ALL SELECT 'session_revocations'::regclass, ctid FROM session_revocations WHERE user_id = target_id
        UNION ALL SELECT 'password_recovery_codes'::regclass, ctid FROM password_recovery_codes WHERE user_id = target_id
        UNION ALL SELECT 'auth_password_attempts'::regclass, a.ctid FROM auth_password_attempts a
            WHERE a.user_id = target_id OR a.code_hash IN (SELECT code_hash FROM password_recovery_codes WHERE user_id = target_id)
        UNION ALL SELECT 'account_registrations'::regclass, ctid FROM account_registrations WHERE user_id = target_id
        UNION ALL SELECT 'admin_audit_events'::regclass, ctid FROM admin_audit_events
            WHERE target_user_id = target_id OR actor_user_id = target_id
        UNION ALL SELECT 'operational_request_events'::regclass, ctid FROM operational_request_events
            WHERE user_id = target_id OR task_id IN (SELECT id FROM tasks WHERE project_id = ANY(owned_projects))
        UNION ALL SELECT 'model_budgets'::regclass, ctid FROM model_budgets WHERE user_id = target_id AND project_id IS NULL
        UNION ALL SELECT 'storage_policies'::regclass, ctid FROM storage_policies
            WHERE (scope_type = 'user' AND scope_id = target_id) OR (scope_type = 'project' AND scope_id = ANY(owned_projects))
        UNION ALL SELECT 'storage_policy_events'::regclass, ctid FROM storage_policy_events
            WHERE (scope_type = 'user' AND scope_id = target_id) OR (scope_type = 'project' AND scope_id = ANY(owned_projects))
        UNION ALL SELECT 'project_assignment_events'::regclass, ctid FROM project_assignment_events
            WHERE actor_id = target_id OR previous_analyst_id = target_id OR analyst_id = target_id
        UNION ALL SELECT 'admin_usage_summaries'::regclass, s.ctid FROM admin_usage_summaries s
            WHERE s.actor_user_id = target_id OR s.filters->>'user_id' = target_id
              OR s.filters->>'project_id' = ANY(owned_projects)
              OR s.filters->>'task_id' IN (SELECT id FROM tasks WHERE project_id = ANY(owned_projects))
              OR s.source_manifest->'calls' @> jsonb_build_array(jsonb_build_object(
                  'captured_projection', jsonb_build_object('user_id', target_id)))
        UNION ALL SELECT 'admin_configuration_bindings'::regclass, b.ctid FROM admin_configuration_bindings b
            JOIN (
                SELECT 'writing_bundle' AS kind, id FROM manuscript_writing_bundles WHERE project_id = ANY(owned_projects)
                UNION ALL SELECT 'review_round', id FROM review_rounds WHERE project_id = ANY(owned_projects)
                UNION ALL SELECT 'school_confirmation', id FROM school_template_confirmations WHERE project_id = ANY(owned_projects)
                UNION ALL SELECT 'journal_confirmation', id FROM journal_targets WHERE project_id = ANY(owned_projects)
            ) related ON b.kind = related.kind AND b.object_id = related.id;

    WHILE EXISTS (SELECT 1 FROM pg_temp.account_erase_rows WHERE depth = generation) LOOP
        FOR edge IN
            SELECT f.conrelid AS child, f.confrelid AS parent, scope.attname AS scope_column,
                (SELECT string_agg(format('child.%I = parent.%I', ca.attname, pa.attname), ' AND ')
                 FROM unnest(f.conkey, f.confkey) AS k(child_num, parent_num)
                 JOIN pg_attribute ca ON ca.attrelid = f.conrelid AND ca.attnum = k.child_num
                 JOIN pg_attribute pa ON pa.attrelid = f.confrelid AND pa.attnum = k.parent_num) AS join_condition
            FROM pg_constraint f
            JOIN pg_class c ON c.oid = f.conrelid AND c.relnamespace = app_namespace
            LEFT JOIN pg_attribute scope ON scope.attrelid = c.oid AND scope.attname = 'project_id' AND NOT scope.attisdropped
            WHERE f.contype = 'f' AND EXISTS (
                SELECT 1 FROM pg_temp.account_erase_rows WHERE relation = f.confrelid AND depth = generation)
        LOOP
            EXECUTE format('INSERT INTO pg_temp.account_erase_rows
                SELECT $1, child.ctid, $2 + 1 FROM %s parent
                JOIN pg_temp.account_erase_rows selected ON selected.relation = $3
                    AND selected.depth = $2 AND parent.ctid = selected.row_tid
                JOIN %s child ON %s %s ON CONFLICT DO NOTHING',
                edge.parent::regclass, edge.child::regclass, edge.join_condition,
                CASE WHEN edge.scope_column IS NULL THEN ''
                     ELSE 'WHERE child.project_id IS NULL OR child.project_id = ANY($4)' END)
            USING edge.child, generation, edge.parent, owned_projects;
        END LOOP;
        generation := generation + 1;
    END LOOP;

    -- These relationships attribute work in a retained project or system record.
    -- Use one non-login identity so delegated files keep their visibility rules.
    CREATE TEMP TABLE account_erase_attributions (relation oid, column_name name) ON COMMIT DROP;
    FOR attribution IN
        SELECT DISTINCT f.conrelid AS relation, a.attname AS column_name FROM pg_constraint f
        JOIN pg_class c ON c.oid = f.conrelid AND c.relnamespace = app_namespace
        JOIN pg_attribute a ON a.attrelid = f.conrelid AND a.attnum = f.conkey[1]
        WHERE f.contype = 'f' AND f.confrelid = 'users'::regclass AND cardinality(f.conkey) = 1
            AND a.attname IN ('actor_id', 'actor_user_id', 'approved_by', 'assigned_by', 'created_by',
                'decided_by', 'requested_by', 'updated_by', 'upload_actor_id')
    LOOP
        EXECUTE format('SELECT EXISTS (SELECT 1 FROM %s kept WHERE kept.%I = $1 AND NOT EXISTS
            (SELECT 1 FROM pg_temp.account_erase_rows WHERE relation = $2 AND row_tid = kept.ctid))',
            attribution.relation::regclass, attribution.column_name)
        INTO retained_attribution USING target_id, attribution.relation;
        IF retained_attribution THEN
            INSERT INTO pg_temp.account_erase_attributions VALUES (attribution.relation, attribution.column_name);
        END IF;
    END LOOP;

    -- Keep FK triggers enabled. Only pause the existing application seals on rows
    -- selected for erasure, then restore their original mode in this transaction.
    CREATE TEMP TABLE account_erase_seals ON COMMIT DROP AS
        SELECT t.tgrelid AS relation, t.tgname AS name, t.tgenabled AS mode FROM pg_trigger t
        WHERE NOT t.tgisinternal AND t.tgenabled <> 'D' AND (t.tgtype & 24) <> 0
          AND (EXISTS (SELECT 1 FROM pg_temp.account_erase_rows r WHERE r.relation = t.tgrelid)
               OR EXISTS (SELECT 1 FROM pg_temp.account_erase_attributions a WHERE a.relation = t.tgrelid));
    FOR seal IN SELECT * FROM pg_temp.account_erase_seals ORDER BY relation, name LOOP
        EXECUTE format('ALTER TABLE %s DISABLE TRIGGER %I', seal.relation::regclass, seal.name);
    END LOOP;

    -- One statement lets immediate NO ACTION FKs check cycles after all deletes.
    SELECT string_agg(format('erased_%s AS (DELETE FROM %s WHERE ctid IN
        (SELECT row_tid FROM pg_temp.account_erase_rows WHERE relation = %s))', relation, relation::regclass, relation), ',')
      INTO delete_queries FROM (SELECT DISTINCT relation FROM pg_temp.account_erase_rows) relations;
    IF delete_queries IS NOT NULL THEN
        EXECUTE 'WITH ' || delete_queries || ' SELECT 1';
    END IF;
    DELETE FROM auth_login_attempts WHERE email = target.email;
    UPDATE project_assignments SET analyst_id = NULL, revision = revision + 1,
        updated_by = operator_id, updated_at = clock_timestamp() WHERE analyst_id = target_id;

    IF EXISTS (SELECT 1 FROM pg_temp.account_erase_attributions) THEN
        INSERT INTO users(id, email, password_hash, role, active, created_at, updated_at)
        VALUES (anonymous_id, anonymous_id, '', 'analyst', false,
            extract(epoch FROM clock_timestamp()), extract(epoch FROM clock_timestamp()))
        ON CONFLICT (id) DO NOTHING;
        FOR attribution IN SELECT * FROM pg_temp.account_erase_attributions LOOP
            request_key_sql := CASE attribution.relation
                WHEN 'file_upload_batches'::regclass THEN ', idempotency_key = ''erased:'' || id'
                WHEN 'file_structure_versions'::regclass THEN ', idempotency_key = ''erased:'' || id'
                WHEN 'file_deletion_requests'::regclass THEN ', idempotency_key = ''erased:'' || id'
                WHEN 'report_collections'::regclass THEN ', creation_key = ''erased:'' || id'
                WHEN 'admin_configuration_events'::regclass THEN ', request_key = ''erased:'' || id'
                WHEN 'delivery_artifact_sources'::regclass THEN ', request_key = ''erased:'' || file_id'
                ELSE '' END;
            EXECUTE format('UPDATE %s SET %I = $2 %s WHERE %I = $1', attribution.relation::regclass,
                attribution.column_name, request_key_sql, attribution.column_name) USING target_id, anonymous_id;
        END LOOP;
    END IF;

    FOR seal IN SELECT * FROM pg_temp.account_erase_seals ORDER BY relation, name LOOP
        EXECUTE format('ALTER TABLE %s ENABLE %sTRIGGER %I', seal.relation::regclass,
            CASE seal.mode WHEN 'A' THEN 'ALWAYS ' WHEN 'R' THEN 'REPLICA ' ELSE '' END, seal.name);
    END LOOP;
    UPDATE users SET active = false WHERE id = target_id;
    INSERT INTO account_deletions(user_id, assets) VALUES (target_id, asset_plan);
    RETURN NULL;
END;
$$;
