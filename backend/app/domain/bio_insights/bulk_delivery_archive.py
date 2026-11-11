"""Assemble an owner-scoped delivery from immutable scientific packages."""
import csv
from contextlib import ExitStack
from pathlib import Path
import tempfile
import zipfile

from app.adapters.bio_analysis_store import BioAnalysisStore
from app.adapters.bio_insights_reproduction import ReproductionArchive
from app.adapters.bio_insights_store import invalid
from app.domain.files import require_file

from .bulk_results import BULK_DIRECTIONS, bulk_row_class
from .contracts import BulkSelection
from .reproducibility import BioInsightReproductionService
from .results import checked_members
from .sources import InsightSourceReader


README = '''# Bulk RNA-seq project delivery

`report/facts.json` records the frozen comparison, figures, QC, filters, resources,
sensitivity and evidence selections. `report/report.docx` uses the same facts digest.
`tables/` preserves all columns of the selected rows of each contrast in original
order. Complete unfiltered result tables are in the corresponding `results/` ZIP.
See `package.json` for exact file hashes, contrast-to-table mapping and source IDs.
`tasks/` contains the public event log for each included execution.

Each ZIP under `results/` or `resources/` includes the complete fixed tables,
available original and prepared inputs, software versions and parameters.
`package.json` distinguishes `matched_environment` archives from `fixed_data_only`
archives. A matched environment supplies the exact requirements, source code and
reproduction program. Fixed-data archives preserve the recorded software hashes for
an operator to locate the matching worker.
Extract the selected ZIP to its own directory. Check its README and verify with
the matching `manifest_sha256` in the outer `package.json`. Use the recorded
interpreter and native libraries. Run `reproduce.py verify` and then `recompute`
for the selected task, or `render` for a display-only task. Restricted resources
require manually supplied matching files and are listed in the relevant child ZIP.
The outer archive does not supply the interpreter or install packages.

`sensitivity/` compares fixed outputs at the selected settings. `evidence/` lists
independent analysis and experimental material separately from the reproduction
inputs. Reproducibility establishes computational consistency for the supplied
inputs. Independent cohorts, biological conclusions and experimental validation
require separate review.
'''


def add_generated(archive, name, stream):
    size = stream.seek(0, 2)
    stream.seek(0)
    return archive.add_stream(name, stream, size_bytes=size)


def add_filtered_tables(archive, path, source_sha256, contrasts):
    """Filter once across all contrasts, preserving the exact published fields."""
    entries = {item['contrast_id']: (item, BulkSelection.model_validate(item['selection'])) for item in contrasts}
    counts = dict.fromkeys(entries, 0)
    try:
        with ExitStack() as stack:
            source = stack.enter_context(Path(path).open(encoding='utf-8-sig', newline=''))
            rows = csv.DictReader(source, delimiter='\t', strict=True)
            fields = rows.fieldnames or []
            if len(fields) != len(set(fields)) or not {'contrast_id', 'row_key', 'feature_id', 'tested',
                    'test_status', 'numerator', 'denominator', 'effect_value',
                    *(item.q_column for _, item in entries.values())}.issubset(fields):
                raise invalid()
            tables = {key: stack.enter_context(tempfile.TemporaryFile(mode='w+t', encoding='utf-8', newline=''))
                      for key in entries}
            writers = {key: csv.DictWriter(stream, fields, delimiter='\t', lineterminator='\n')
                       for key, stream in tables.items()}
            for writer in writers.values():
                writer.writeheader()
            for row in rows:
                key = row['contrast_id']
                if None in row or None in row.values() or key not in entries:
                    raise invalid()
                item, selection = entries[key]
                if (row['numerator'], row['denominator']) != (item['numerator'], item['denominator']):
                    raise invalid()
                category = bulk_row_class(row, selection)
                if category in BULK_DIRECTIONS and selection.direction in ('both', category):
                    writers[key].writerow(row)
                    counts[key] += 1

            records = []
            for index, (key, stream) in enumerate(tables.items(), start=1):
                item, selection = entries[key]
                expected_count = item['counts']['deg' if selection.direction == 'both' else selection.direction]
                if counts[key] != expected_count:
                    raise invalid()
                stream.flush()
                record = add_generated(archive, f'tables/contrast-{index:02d}-filtered.tsv', stream.buffer)
                records.append({**record, 'source_sha256': source_sha256, 'rows': counts[key],
                                'selection': selection.model_dump(mode='json')})
            return records
    except (csv.Error, OSError, UnicodeError) as exc:
        raise invalid() from exc


class BulkDeliveryArchive(BioInsightReproductionService):
    def _add_reproduction(self, archive, project, identifier, *, resource=False):
        package = self.export(project, identifier, resource=resource, allow_data_only=True)
        name = ('resources' if resource else 'results') + f'/{identifier}.zip'
        with package['file'] as handle:
            record = add_generated(archive, name, handle)
        return dict(**record, version_id=identifier, manifest_sha256=package['manifest_sha256'],
                    analysis_inputs_self_contained=package['analysis_inputs_self_contained'],
                    reproduction_state=package['reproduction_state'])

    def _add_task_events(self, archive, task_ids):
        for task_id in sorted(task_ids):
            events = []
            cursor = 0
            while True:
                page = self.store.events(task_id, after=cursor, limit=100)
                events.extend(page['items'])
                if not page['has_more']:
                    break
                cursor = page['next_cursor']
            archive.add_json(f'tasks/{task_id}-events.json', dict(task_id=task_id, events=events))

    def _add_evidence(self, archive, db, project, evidence):
        if not evidence:
            return
        reader = InsightSourceReader(self.assets)
        references = []
        for item in evidence:
            if item['kind'] == 'experimental_material':
                file = dict(require_file(db, project, item['source_id']))
                if file['sha256'] != item['sha256']:
                    raise invalid()
                restricted = db.execute("""SELECT 1 FROM bio_resource_members m
                    JOIN bio_resource_versions v ON v.id=m.resource_version_id AND v.project_id=m.project_id AND v.user_id=m.user_id
                    WHERE m.project_id=%s AND m.user_id=%s AND m.role='original_resource' AND m.sha256=%s
                      AND v.usage_json->'redistribution_allowed' IS DISTINCT FROM 'true'::jsonb LIMIT 1""",
                    (project, self.store.user_id, file['sha256'])).fetchone()
                if restricted:
                    references.append({**item, 'distribution': 'reference_only_resource_license'})
                    continue
                name = f'evidence/materials/{file["id"]}.bin'
                if file['uploader_id'] is None:
                    record = archive.add_bytes(name, self.assets.original(file))
                else:
                    _, _, members = reader.original(db, project, file['id'])
                    member = members['original_file']
                    record = archive.add_file(name, member['path'], member)
                references.append({**item, 'archive_path': record['path']})
            else:
                references.append(item)
        archive.add_json('evidence/references.json', references)

    def export_delivery(self, project, facts, word, *, change_table=None, destination=None):
        archive = ReproductionArchive(compression=zipfile.ZIP_DEFLATED, compresslevel=1, destination=destination)
        try:
            comparison = facts['comparison_version_id']
            results = list(dict.fromkeys([comparison, *facts['result_version_ids']]))
            processed_ids = list(facts['processed_version_ids'])
            if facts['sensitivity']:
                scenario = facts['sensitivity']['scenario']
                results = list(dict.fromkeys([*results, scenario['result_version_id']]))
                processed_ids = list(dict.fromkeys([*processed_ids, *(item['version_id'] for item in scenario['processed_sources'])]))

            task_ids = set()
            with self.store.connection() as db:
                self.store.require_project(db, project)
                result_rows = [self.require(db, 'bio_insight_result_versions', project, version_id) for version_id in results]
                resource_rows = [self.require(db, 'bio_resource_versions', project, version_id)
                                 for version_id in facts['resource_version_ids']]
                task_ids.update(row['task_id'] for row in (*result_rows, *resource_rows))
                bio = BioAnalysisStore(self.assets)
                for version_id in processed_ids:
                    row = bio.require(db, 'bio_processed_dataset_versions', project, version_id)
                    task_ids.add(row['task_id'])
                    imported = db.execute("""SELECT i.task_id FROM bio_dataset_versions v
                        JOIN bio_imports i ON i.id=v.import_id AND i.project_id=v.project_id
                        JOIN tasks t ON t.id=i.task_id AND t.project_id=i.project_id AND t.user_id=%s
                        WHERE v.project_id=%s AND v.id=%s""",
                        (self.store.user_id, project, row['raw_dataset_version_id'])).fetchone()
                    if imported:
                        task_ids.add(imported['task_id'])
                task_ids.update(item['task_id'] for item in facts['evidence'] if item['kind'] == 'independent_analysis')
                _, members = checked_members(self, db, project, result_rows[0])
                full = next((item for item in members if item['key'] == 'comparison_results' and item['format'] == 'tsv'), None)
                if not full:
                    raise invalid('bio_insight_source_incomplete', 422)
                filters = add_filtered_tables(archive, self.objects.path(full['object_key']), full['sha256'], facts['contrasts'])
                self._add_evidence(archive, db, project, facts['evidence'])

            packages = [self._add_reproduction(archive, project, version_id) for version_id in results]
            packages.extend(self._add_reproduction(archive, project, row['id'], resource=True) for row in resource_rows)
            self._add_task_events(archive, task_ids)
            if change_table is not None:
                add_generated(archive, 'sensitivity/feature-changes.tsv', change_table)
            archive.add_bytes('README.md', README.encode('utf-8'))
            archive.add_json('report/facts.json', facts)
            archive.add_bytes('report/report.docx', word)
            self_contained = all(item['analysis_inputs_self_contained'] for item in packages)
            manifest = dict(schema_version=1, kind='bulk_rna_seq_delivery', project_id=project, facts_digest=facts['facts_digest'],
                            comparison_version_id=comparison, processed_version_ids=processed_ids, packages=packages,
                            filters=filters, analysis_inputs_self_contained=self_contained, external_locked_runtime_required=True)
            handle, manifest_sha256 = archive.finish(manifest)
            return dict(file=handle, manifest_sha256=manifest_sha256, analysis_inputs_self_contained=self_contained)
        except BaseException:
            archive.close()
            raise
