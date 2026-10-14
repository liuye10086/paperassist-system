"""Optional provenance that does not alter historical serialization."""
from pydantic import BaseModel, ConfigDict, Field, model_serializer
from app.domain.analysis_sources import OptionalAnalysisSource


class PlanReference(BaseModel):
    model_config = ConfigDict(strict=True,extra='forbid')
    plan_id: str = Field(min_length=1,max_length=64)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    resolutions: dict[str,str]


class PlannedAnalysisSource(OptionalAnalysisSource):
    analysis_plan: PlanReference | None = None

    @model_serializer(mode='wrap')
    def serialize_plan(self,handler):
        value=handler(self)
        for name in ('source','analysis_plan'):
            if getattr(self,name) is None: value.pop(name,None)
        return value
