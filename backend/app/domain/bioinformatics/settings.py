"""Frozen limits: deployment overrides may only tighten CR-B01 bounds."""
from pydantic import BaseModel, ConfigDict, Field


MAX_BULK_IMPORT_REQUEST_BYTES = 2 * 1024**2
MAX_BULK_METADATA_CELLS = 5_000_000


class BioLimits(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    max_upload_bytes: int = Field(default=128 * 1024 * 1024, gt=0, le=128 * 1024 * 1024)
    max_members: int = Field(default=256, gt=0, le=256)
    max_member_bytes: int = Field(default=268435456, gt=0, le=268435456)
    max_expanded_bytes: int = Field(default=536870912, gt=0, le=536870912)
    max_tabular_file_bytes: int = Field(default=128 * 1024 * 1024, gt=0, le=128 * 1024 * 1024)
    max_tabular_expanded_bytes: int = Field(default=256 * 1024 * 1024, gt=0, le=256 * 1024 * 1024)
    max_bulk_matrix_cells: int = Field(default=5_000_000, gt=0, le=5_000_000)
    max_bulk_observations: int = Field(default=512, gt=0, le=512)
    max_features: int = Field(default=100000, gt=0, le=100000)
    max_observations: int = Field(default=100000, gt=0, le=100000)
    max_entries: int = Field(default=10000000, gt=0, le=10000000)
    max_image_pixels: int = Field(default=16000000, gt=0, le=16000000)
    timeout_seconds: int = Field(default=180, gt=0, le=180)
    cpu_seconds: int = Field(default=120, gt=0, le=120)
    memory_bytes: int = Field(default=1073741824, gt=0, le=1073741824)
    max_output_json_bytes: int = Field(default=2097152, gt=0, le=2097152)
