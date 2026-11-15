from app.adapters.bio_objects import BioObjects
from app.domain.bioinformatics.contracts import conflict


class ResearchObjects(BioObjects):
    prefix='research-results'

    def open_verified(self, record):
        """Verify the same handle that will be consumed by the download."""
        try:
            handle = self.path(record['object_key']).open('rb')
            try:
                self._verify_stream(record, handle)
                handle.seek(0)
                return handle
            except BaseException:
                handle.close()
                raise
        except OSError as exc:
            raise conflict() from exc
