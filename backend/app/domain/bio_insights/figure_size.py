from pydantic import BaseModel, ConfigDict, Field, model_validator


def validate_figure_size(width_inches, height_inches, dpi):
    width = round(width_inches * dpi)
    height = round(height_inches * dpi)
    if max(width, height) > 4096 or width * height > 16_000_000:
        raise ValueError('Figure exceeds 4096 pixels per side or 16 million total pixels')


class PlotSize(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True, allow_inf_nan=False)
    width_inches: float = Field(ge=2, le=20)
    height_inches: float = Field(ge=2, le=20)
    dpi: int = Field(ge=72, le=600)

    @model_validator(mode='after')
    def within_pixel_budget(self):
        validate_figure_size(self.width_inches, self.height_inches, self.dpi)
        return self
