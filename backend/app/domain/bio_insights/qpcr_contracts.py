"""Frozen long-table qPCR design; never an expression-matrix adapter."""
from typing import Literal
import math
from pydantic import Field, model_validator
from .quantitative_contracts import QuantitativeModel, Identifier

class QpcrColumns(QuantitativeModel):
    plate_id: Identifier
    well: Identifier
    sample_id: Identifier
    biological_unit_id: Identifier
    target_id: Identifier
    cq: Identifier
    detection_status: Identifier
    technical_replicate: Identifier
    condition: Identifier
    pair_id: Identifier | None = None
    time: Identifier | None = None
    dose: Identifier | None = None

class QpcrContrast(QuantitativeModel):
    contrast_id: Identifier
    name: str = Field(min_length=1,max_length=500)
    numerator: Identifier
    denominator: Identifier

class QpcrEfficiency(QuantitativeModel):
    value: float = Field(gt=0)
    representation: Literal['amplification_factor','fraction','percent']
    source: str = Field(min_length=1,max_length=4000)

    @property
    def factor(self):
        return self.value if self.representation=='amplification_factor' else 1+self.value/(100 if self.representation=='percent' else 1)

    @model_validator(mode='after')
    def valid_factor(self):
        if not math.isfinite(self.factor) or self.factor<=1:raise ValueError('qpcr_efficiency_factor_requires_finite_above_one')
        return self

class QpcrExclusion(QuantitativeModel):
    plate_id: Identifier
    well: Identifier
    reason: str = Field(min_length=1,max_length=1000)

class QpcrOriginalCheck(QuantitativeModel):
    sample_id: Identifier
    plate_id: Identifier
    target_id: Identifier
    metric: Literal['delta_cq','delta_delta_cq','relative_quantity','log2_quantity']
    original_value: float
    unit: Literal['Cq','fold','log2']
    tolerance: float = Field(ge=0,le=1000000)
    precision_basis: str = Field(min_length=1,max_length=4000)
    original_report_source: str = Field(min_length=1,max_length=4000)

class QpcrConfig(QuantitativeModel):
    kind: Literal['comparison']='comparison'
    schema_version: Literal[3]=3
    mode: Literal['qpcr']='qpcr'
    recipe: Literal['qpcr_relative_quantification_v1']='qpcr_relative_quantification_v1'
    output_language: Literal['zh-CN','en']='zh-CN'
    file_source_id: Identifier
    parse_version_id: Identifier
    sheet: Identifier | None = None
    columns: QpcrColumns
    targets: list[Identifier] = Field(min_length=1,max_length=100)
    references: list[Identifier] = Field(min_length=1,max_length=20)
    reference_basis: str = Field(min_length=1,max_length=4000)
    calibrator_conditions: list[Identifier] = Field(default_factory=list,max_length=30)
    calibrator_sample_ids: list[Identifier] = Field(default_factory=list,max_length=10000)
    quantification: Literal['delta_delta_cq','efficiency']='delta_delta_cq'
    equal_efficiency_confirmed: bool=False
    equal_efficiency_basis: str = Field(default='',max_length=4000)
    efficiencies: dict[Identifier,QpcrEfficiency] = Field(default_factory=dict,max_length=120)
    cross_plate: Literal['separate','comparable']='separate'
    cross_plate_basis: str = Field(default='',max_length=4000)
    design: Literal['independent','paired']='independent'
    paired_plate_policy: Literal['separate','within_plate_differences']='separate'
    paired_plate_basis: str = Field(default='',max_length=4000)
    method: Literal['welch_t','mann_whitney_u','paired_t','wilcoxon']='welch_t'
    independence_confirmed: bool=False
    independence_basis: str = Field(default='',max_length=4000)
    contrasts: list[QpcrContrast] = Field(min_length=1,max_length=10)
    family_contrast_ids: list[Identifier] = Field(min_length=1,max_length=10)
    excluded_wells: list[QpcrExclusion] = Field(default_factory=list,max_length=10000)
    original_checks: list[QpcrOriginalCheck] = Field(default_factory=list,max_length=10000)
    detected_values: list[Identifier] = Field(default_factory=lambda:['detected'],min_length=1,max_length=20)
    nondetected_values: list[Identifier] = Field(default_factory=lambda:['undetermined','not_detected'],min_length=1,max_length=20)
    na_values: list[str] = Field(default_factory=lambda:['','NA','N/A','Undetermined','undetermined'],max_length=30)
    technical_sd_warning: float = Field(default=0.5,gt=0,le=100)
    time_unit: str = Field(default='',max_length=200)
    dose_unit: str = Field(default='',max_length=200)
    namespace: Identifier
    reference_version: Identifier
    species_taxon_id: int | None = Field(default=None,ge=1)

    @model_validator(mode='after')
    def coherent(self):
        if len(self.model_dump_json().encode())>4*1024**2:raise ValueError('qpcr_config_limit')
        ids=[c.contrast_id for c in self.contrasts]
        if len(ids)!=len(set(ids)) or len(self.family_contrast_ids)!=len(set(self.family_contrast_ids)) or set(ids)!=set(self.family_contrast_ids):raise ValueError('qpcr_complete_family_required')
        assays=self.targets+self.references
        if len(assays)!=len(set(assays)):raise ValueError('qpcr_duplicate_or_overlapping_assays')
        columns=[c for c in self.columns.model_dump().values() if c]
        if len(columns)!=len(set(columns)):raise ValueError('qpcr_duplicate_columns')
        if bool(self.calibrator_conditions)==bool(self.calibrator_sample_ids):raise ValueError('qpcr_choose_calibrator_conditions_or_samples')
        if self.quantification=='delta_delta_cq' and (not self.equal_efficiency_confirmed or not self.equal_efficiency_basis.strip()):raise ValueError('qpcr_equal_efficiency_basis_required')
        if self.quantification=='efficiency' and set(self.efficiencies)!=set(assays):raise ValueError('qpcr_each_assay_efficiency_required')
        if self.cross_plate=='comparable' and not self.cross_plate_basis.strip():raise ValueError('qpcr_cross_plate_basis_required')
        if not self.independence_confirmed or not self.independence_basis.strip():raise ValueError('qpcr_biological_units_confirmation_required')
        if (self.method in ('paired_t','wilcoxon'))!=(self.design=='paired'):raise ValueError('qpcr_method_design_mismatch')
        if self.design=='paired' and not self.columns.pair_id:raise ValueError('qpcr_pair_column_required')
        if self.paired_plate_policy=='within_plate_differences' and (self.design!='paired' or self.cross_plate!='separate' or not self.paired_plate_basis.strip()):raise ValueError('qpcr_within_plate_pair_basis_required')
        if self.columns.time and not self.time_unit.strip() or self.columns.dose and not self.dose_unit.strip():raise ValueError('qpcr_time_dose_unit_required')
        if set(self.detected_values)&set(self.nondetected_values):raise ValueError('qpcr_detection_status_overlap')
        if any(c.numerator==c.denominator for c in self.contrasts):raise ValueError('qpcr_identical_conditions')
        for check in self.original_checks:
            expected='fold' if check.metric=='relative_quantity' else 'log2' if check.metric=='log2_quantity' else 'Cq'
            if check.unit!=expected:raise ValueError('qpcr_original_report_unit_mismatch')
        return self
