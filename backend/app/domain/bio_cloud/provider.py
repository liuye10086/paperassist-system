"""Safe provider failures; never retain third-party exception text."""
import re
from typing import Any, BinaryIO, Protocol


# Remote task IDs are opaque. AWS HealthOmics currently returns decimal IDs,
# while future providers may return UUID-like or namespaced job IDs.
PROVIDER_RUN_ID_PATTERN = r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}'
PROVIDER_RUN_STATES = frozenset({'PENDING', 'STARTING', 'RUNNING', 'STOPPING', 'COMPLETED', 'DELETED', 'CANCELLED', 'FAILED'})


class BioCloudProvider(Protocol):
    """Transport boundary shared by cloud storage and asynchronous workflows.

    Provider-specific SDK objects and credentials never cross this interface.
    Workflow chemistry/parameters/output layouts belong to approved profiles.
    """
    def begin_upload(self, key: str) -> str: ...
    def sign_part(self, key: str, upload_id: str, number: int, checksum: str) -> dict[str, Any]: ...
    def list_parts(self, key: str, upload_id: str) -> list[dict[str, Any]]: ...
    def complete_upload(self, key: str, upload_id: str, parts: list[dict[str, Any]]) -> dict[str, Any]: ...
    def head_input(self, key: str) -> dict[str, Any]: ...
    def abort_upload(self, key: str, upload_id: str) -> None: ...
    def put_samplesheet(self, key: str, content: bytes) -> str: ...
    def submit_run(self, profile: Any, *, request_id: str, task_id: str, output_prefix: str, parameters: dict[str, str]) -> dict[str, Any]: ...
    def get_run(self, run_id: str) -> dict[str, Any]: ...
    def cancel_run(self, run_id: str) -> None: ...
    def list_outputs(self, run_output_uri: str) -> list[dict[str, Any]]: ...
    def stream_output(self, key: str, *, expected_etag: str | None = None) -> BinaryIO: ...
    def close(self) -> None: ...


class ProviderError(Exception):
    def __init__(self, code: str, *, uncertain: bool = False):
        self.code = code if re.fullmatch(r'[a-z][a-z0-9_]{0,79}', code) else 'provider_error'
        self.uncertain = uncertain
        super().__init__(self.code)


def provider_run_id(value: Any) -> str:
    """Validate an opaque, non-secret remote task identity."""
    if not isinstance(value, str) or not re.fullmatch(PROVIDER_RUN_ID_PATTERN, value):
        raise ProviderError('invalid_provider_run_id')
    return value


def output_record(value: Any) -> dict[str, Any]:
    """Validate the immutable result listing consumed by the collector."""
    if (not isinstance(value, dict) or not isinstance(value.get('key'), str)
            or not value['key'] or type(value.get('size_bytes')) is not int
            or value['size_bytes'] <= 0 or not isinstance(value.get('etag'), str)
            or not value['etag']):
        raise ProviderError('invalid_output_record')
    return dict(key=value['key'], size_bytes=value['size_bytes'], etag=value['etag'])
