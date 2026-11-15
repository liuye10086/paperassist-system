"""Synthetic presentation records for tests of the offline research exporter."""
from uuid import uuid4

import pytest


READER_SECTIONS = (
    'abstract', 'design_and_data', 'quality_control', 'methods_summary',
    'key_findings', 'limitations', 'reader_cautions',
)


def sample_reader_record(base):
    en=base['language']=='en'
    sections=[
        'The report summarizes the frozen observations.',
        'Only the selected observations are available for review.',
        'Check whether missing observations affect the comparison.',
        'The source provides the saved observations for inspection.',
        'The recorded observations should be interpreted within their study design.',
        'The available records do not establish an independent sample count.',
        'Use the original records to examine the context of each observation.',
    ] if en else [
        '报告汇总已固定的观察结果。',
        '仅选定的观察记录可供核对。',
        '请核对缺失观测是否影响比较。',
        '查看来源保存的原始观测。',
        '结果需要结合当前研究设计解读。',
        '已有记录不足以确认独立样本数。',
        '请结合原始记录核对各项观察的背景。',
    ]
    figures=[]
    for index,_ in enumerate(base['figures'],1):
        title=f'Observation panel {index}' if en else f'第 {index} 张观察图'
        reading='Read the horizontal and vertical axes together.' if en else '结合横轴与纵轴一起读图。'
        observations='The plotted points indicate the selected observations.' if en else '图中的数据点表示选定观察。'
        interpretation='Shown values describe the selected observations.' if en else '图值描述选定的观测。'
        limitations='The image alone cannot establish an independent sample count.' if en else '仅凭图件无法确认独立样本数。'
        figures.append(dict(number=index,title=title,reading=reading,observations=observations,
            interpretation=interpretation,limitations=limitations,
            caption='\n'.join((reading,observations,interpretation,limitations))))
    return dict(standard_version='reader-report-v1',binding_sha256='a'*64,
        narrative=dict(zip(READER_SECTIONS,sections)),figures=figures,
        provenance=dict(origin='model',provider='fixture',model='synthetic-model',model_call_id='fixture-call'))


@pytest.fixture
def research_reader_narrative(monkeypatch):
    from app.domain.reader_reports.service import ReaderReportService
    narrative_id=str(uuid4())

    def record_for(_service,_db,_project,identifier,base_content):
        assert identifier==narrative_id
        return sample_reader_record(base_content)

    monkeypatch.setattr(ReaderReportService,'record_for',record_for)
    return narrative_id
