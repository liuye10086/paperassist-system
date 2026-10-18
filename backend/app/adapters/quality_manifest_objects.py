"""Complete immutable impact receipts, separate from bounded dataset objects."""
import json
from app.adapters.prepared_dataset_objects import PreparedDatasetObjects, changed
from app.domain.dataset_preparation.quality_contracts import QualityManifest, MAX_MANIFEST_BYTES

class QualityManifestObjects(PreparedDatasetObjects):
    prefix = 'quality-manifests'
    max_bytes = MAX_MANIFEST_BYTES

    def _validate_content(self, content):
        if type(content) is not bytes or not 0 < len(content) <= self.max_bytes:
            raise changed('完整质量影响明细为空或超过16MiB限制，请缩小本轮处理范围。')
        try:
            return QualityManifest.model_validate(json.loads(content))
        except (ValueError,TypeError,RecursionError) as exc:
            raise changed('完整质量影响明细核验失败。') from exc

    def read(self,record):
        content,obj=super().read(record)
        if 'entry_count' in record and record['entry_count'] != len(obj.entries):
            raise changed('完整影响条目数量不一致。')
        return content,obj
