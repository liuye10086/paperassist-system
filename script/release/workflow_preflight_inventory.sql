-- B04/B05 pre-release inventory. Supply the approved read-only service name:
-- psql -X -v ON_ERROR_STOP=1 -d "service=<approved_service>" -f script/release/workflow_preflight_inventory.sql
-- A nonzero GS501 count requires reviewing those versions again before release.
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL search_path TO pg_catalog, public;

SELECT current_database() AS database_name, current_setting('transaction_read_only') AS read_only,
       transaction_timestamp() AS observed_at, version_num AS migration_head
FROM public.alembic_version;

SELECT count(*) AS gs501_language_reviewed_versions
FROM public.manuscript_versions
WHERE snapshot_json #>> '{thesis_context,confirmation,format_profile}' = 'bsu-gs501-academic-masters-2026'
  AND nullif(snapshot_json #>> '{writing_provenance,language_review_id}', '') IS NOT NULL;

SELECT count(*) AS blind_word_exports
FROM public.manuscript_exports
WHERE metadata_json #>> '{presentation,binding,review_mode}' = 'blind';

SELECT count(*) AS blind_tasks,
       count(*) FILTER (WHERE status = 'failed') AS failed,
       count(*) FILTER (WHERE status IN ('waiting_input', 'waiting_confirmation')) AS waiting,
       count(*) FILTER (WHERE status = 'succeeded') AS succeeded
FROM public.tasks
WHERE input_snapshot #>> '{presentation,binding,review_mode}' = 'blind';

WITH blind_snapshots AS (
    SELECT s.id, s.project_id, s.delivery_id
    FROM public.delivery_snapshots AS s
    WHERE s.snapshot_json->>'mode' = 'blind'
       OR EXISTS (
           SELECT 1 FROM jsonb_array_elements(s.snapshot_json->'members') AS member
           WHERE member->>'review_mode' = 'blind'
       )
)
SELECT count(*) AS blind_snapshots, count(*) FILTER (WHERE EXISTS (
    SELECT 1 FROM public.customer_delivery_publications AS p
    WHERE (p.project_id, p.delivery_id, p.snapshot_id) = (s.project_id, s.delivery_id, s.id)
)) AS published_blind_snapshots
FROM blind_snapshots AS s;

SELECT count(*) FILTER (WHERE role = 'user') AS legacy_user_accounts,
       count(*) FILTER (WHERE review_status = 'pending') AS pending_accounts,
       count(*) FILTER (WHERE review_status = 'pending' AND EXISTS (
           SELECT 1 FROM public.account_registrations AS r WHERE r.user_id = u.id
       )) AS pending_registrations
FROM public.users AS u;

WITH old_returns AS (
    SELECT project_id, user_id, previous_round_id
    FROM public.review_round_user_returns
    WHERE idempotency_key = concat('return:', previous_round_id, ':', base_version_id, ':', document_version_id)
)
SELECT count(*) AS old_key_returns, count(*) FILTER (WHERE NOT EXISTS (
    SELECT 1 FROM public.review_round_continuations AS c
    WHERE (c.project_id, c.user_id, c.previous_round_id) = (r.project_id, r.user_id, r.previous_round_id)
)) AS old_key_returns_without_next_round
FROM old_returns AS r;

WITH published_analysis AS (
    SELECT s.id AS snapshot_id, s.delivery_id, s.snapshot_json->'members' AS members
    FROM public.customer_delivery_publications AS p
    JOIN public.delivery_snapshots AS s
      ON (s.project_id, s.delivery_id, s.id) = (p.project_id, p.delivery_id, p.snapshot_id)
    JOIN public.research_deliveries AS d ON (d.project_id, d.id) = (p.project_id, p.delivery_id)
    WHERE d.kind = 'analysis'
), formats AS (
    SELECT lower(coalesce(nullif(member->>'format', ''), 'unknown')) AS format, count(*) AS members
    FROM published_analysis CROSS JOIN LATERAL jsonb_array_elements(members) AS member
    GROUP BY 1
)
SELECT (SELECT count(DISTINCT delivery_id) FROM published_analysis) AS published_analysis_deliveries,
       (SELECT count(*) FROM published_analysis) AS published_snapshots,
       coalesce(sum(members), 0) AS all_members,
       coalesce(sum(members) FILTER (WHERE format = 'docx'), 0) AS word_members,
       coalesce(sum(members) FILTER (WHERE format <> 'docx'), 0) AS other_members,
       coalesce(jsonb_object_agg(format, members), '{}'::jsonb) AS members_by_format
FROM formats;

ROLLBACK;
