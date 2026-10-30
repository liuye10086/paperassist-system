"""Fenced bio candidate persistence through the existing storage ledger."""
import copy
import hashlib
from pathlib import Path
from uuid import UUID, uuid5

from app.adapters.task_store import DatasetTaskAssets, TaskStore
from app.adapters.bio_lease import renew_bio_lease
from app.domain.bioinformatics.contracts import canonical, conflict, validate_snapshot, validate_v2_representation
from app.domain.bioinformatics.parser_contracts import PARSER_VERSION
from app.domain.bioinformatics.service import BioDatasetService, append_checkpoint, latest_checkpoint
from app.domain.storage_governance.deterministic import authorize_rebuild, explicit_retry
from app.domain.storage_governance.bio_manifest import admit_bio_manifest, settle_bio_manifest
from app.domain.tasks.waits import persist_wait


def build_candidate(task, result, objects):
    """Build deterministic metadata; leaf bodies stay on disk until admitted."""
    snapshot = task["input_snapshot"]
    validate_v2_representation(task, result)
    import_id = snapshot["import_id"]
    namespace = UUID(import_id)
    sources = {f["id"] for f in snapshot["files"]}
    members, leaves, keys = [], [], set()
    for output in result["outputs"]:
        key, path = output["key"], Path(output["path"])
        if (key in keys or output["source_file_id"] not in sources or not output["source_member_name"]
                or path.is_symlink() or not path.is_file() or path.stat().st_size != output["size_bytes"]):
            raise conflict()
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                digest.update(block)
        if digest.hexdigest() != output["sha256"]:
            raise conflict()
        member = {k: output[k] for k in ("key", "role", "format", "compression", "verification_state",
                  "source_file_id", "source_member_name", "sha256", "size_bytes")}
        member.update(id=str(uuid5(namespace, key)),
                      object_key=f"bio-datasets/{import_id}/{output['sha256']}.bin")
        objects.path(member["object_key"])
        members.append(member)
        leaves.append({"path": str(path), "record": {k: member[k] for k in ("object_key", "sha256", "size_bytes")}})
        keys.add(key)
    manifest = copy.deepcopy(result["manifest"])
    manifest["members"] = [{k: v for k, v in member.items() if k != "object_key"} for member in members]
    candidate = {"schema_version": 1, "import_id": import_id, "input_sha256": task["input_digest"],
        "parser_version": snapshot['parser_version'], "manifest": manifest, "members": members,
        "summary": {"features": result["n_features"], "observations": result["n_observations"],
                    "stored_entries": result["entry_count"]}, "checks": result["checks"]}
    return candidate, leaves


class BioDatasetExecution:
    def __init__(self, repository):
        self.repository = repository

    def service(self, task):
        return BioDatasetService(DatasetTaskAssets(task["user_id"], self.repository.config,
                                                   self.repository.assets.directory))

    def load(self, lease):
        with self.repository.connection() as db:
            task = self.repository.require_lease(db, lease)
            self.repository.require_owner(db, task)
            validate_snapshot(task)
            checkpoint = latest_checkpoint(db, task)
            files = self.service(task).require_sources(db, task)
        return task, checkpoint, files

    @staticmethod
    def _require_check(current, checkpoint):
        if (current["id"] != checkpoint["id"] or current["next_node"] != "check"
                or current["state_json"].get("candidate") is not None):
            raise conflict()

    def wait(self, lease, checkpoint, result):
        with self.repository.connection() as db:
            task = self.repository.require_lease(db, lease)
            self.repository.require_owner(db, task)
            self._require_check(latest_checkpoint(db, task), checkpoint)
        service = self.service(task)
        candidate, leaves = build_candidate(task, result, service.objects)
        import_id = task["input_snapshot"]["import_id"]
        manifest_content, candidate_content = canonical(candidate["manifest"]), canonical(candidate)
        manifest_ref = service.objects.describe(import_id, manifest_content, json=True)
        candidate_ref = service.objects.describe(import_id, candidate_content, json=True)
        # Multiple index/member references may share one immutable physical leaf.
        unique = {leaf["record"]["object_key"]: leaf for leaf in leaves}
        prefix = "bio_dataset:" + import_id + ":"
        entries = [("bio_dataset", prefix + "leaf:" + leaf["record"]["sha256"], leaf["record"])
                   for leaf in unique.values()]
        entries += [("bio_dataset", prefix + "manifest", manifest_ref),
                    ("bio_dataset", prefix + "candidate", candidate_ref)]
        with self.repository.connection(write=True) as db:
            task = self.repository.require_lease(db, lease)
            progress=lambda:renew_bio_lease(db,lease)
            progress()
            self.repository.require_owner(db, task)
            self._require_check(latest_checkpoint(db, task), checkpoint)
            service.require_sources(db, task, progress=progress)
            service.require_v2_source_root(db, task, candidate)
            if explicit_retry(db, task):
                authorize_rebuild(db, self.repository.assets.directory, task,
                    allowed={"bio_dataset": ("bio-datasets", import_id,
                        prefix + r"(?:leaf:[0-9a-f]{64}|manifest|candidate)")}, progress=progress)
            rows = admit_bio_manifest(db, self.repository.assets.directory, task, entries, progress=progress)
            progress()
        # No bytes enter controlled object storage before complete admission.
        for leaf in unique.values():
            service.objects.write(leaf["record"], Path(leaf["path"]).read_bytes())
        service.objects.write(manifest_ref, manifest_content)
        service.objects.write(candidate_ref, candidate_content)
        with self.repository.connection(write=True) as db:
            task = self.repository.require_lease(db, lease)
            progress=lambda:renew_bio_lease(db,lease)
            progress()
            self.repository.require_owner(db, task)
            current = latest_checkpoint(db, task)
            self._require_check(current, checkpoint)
            service.require_sources(db, task, progress=progress)
            service.require_v2_source_root(db, task, candidate)
            settle_bio_manifest(db, self.repository.assets.directory, task, rows, progress=progress)
            stored = db.execute('''SELECT o.* FROM storage_objects o JOIN storage_references r ON r.object_id=o.id
                WHERE o.object_key=%s AND o.state='present' AND r.project_id=%s AND r.owner_id=%s''',
                (candidate_ref["object_key"], task["project_id"], task["user_id"])).fetchone()
            if (not stored or stored["sha256"] != candidate_ref["sha256"]
                    or stored["size_bytes"] != candidate_ref["size_bytes"]):
                raise conflict()
            updated = db.execute('''UPDATE bio_imports SET candidate_object_id=%s
                WHERE id=%s AND task_id=%s AND project_id=%s
                AND (candidate_object_id IS NULL OR candidate_object_id=%s)''',
                (stored["id"], import_id, task["id"], task["project_id"], stored["id"]))
            if updated.rowcount != 1:
                raise conflict()
            progress()
            previous = task["revision"]
            task.update(status="waiting_confirmation", phase="parse", revision=previous + 1,
                        updated_at=max(self.repository.now(db), task["updated_at"]),
                        reason_code="confirmation_required", error_code=None)
            state = {**current["state_json"], "candidate": candidate_ref}
            append_checkpoint(db, task, "await_confirmation", "await_confirmation", state, current)
            TaskStore.finish_attempt(db, task)
            TaskStore.update_task(db, task, previous)
            TaskStore.append_event(db, task, "waiting")
            persist_wait(db, task)
            return TaskStore.public_task(task)

    def publish(self, lease, checkpoint):
        with self.repository.connection(write=True) as db:
            task = self.repository.require_lease(db, lease)
            progress=lambda:renew_bio_lease(db,lease)
            progress()
            self.repository.require_owner(db, task)
            current = latest_checkpoint(db, task)
            if current["id"] != checkpoint["id"] or current["next_node"] != "publish":
                raise conflict()
            service = self.service(task)
            now = max(self.repository.now(db), task["updated_at"])
            # The service validates the exact accepted candidate and decision,
            # source hashes and dataset CAS, then writes version and done once.
            return service.publish(db, task, current, now, progress=progress)
