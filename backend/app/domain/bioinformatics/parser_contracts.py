"""Private parser boundary; no database, HTTP, or model provider dependencies."""
from dataclasses import dataclass, field
from typing import Any

from app.core.exceptions import StorageError

PARSER_VERSION = "geo_visium_import_v1"


class BioParseError(StorageError):
    def __init__(self, code, detail=""):
        # Only controlled diagnostic labels belong here, never input text/paths.
        super().__init__(code, detail or code, status=422)


@dataclass
class BioParseResult:
    n_features: int
    n_observations: int
    entry_count: int
    feature_ids: list[str]
    feature_symbols: list[str]
    barcodes: list[str]
    in_tissue_barcodes: list[str]
    checks: dict[str, Any]
    outputs: list[dict[str, Any]]
    manifest: dict[str, Any] = field(default_factory=dict)

    def summary(self):
        """The bounded subprocess response contains file indexes, not axis text."""
        return {"parser_version": PARSER_VERSION, "manifest": self.manifest,
                "outputs": self.outputs, "checks": self.checks,
                "n_features": self.n_features, "n_observations": self.n_observations,
                "entry_count": self.entry_count}
