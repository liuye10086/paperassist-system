"""Statistics-only isolated renderer; the eight shared renderer files stay fixed."""
import json
from pathlib import Path
import resource
import sys

resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
resource.setrlimit(resource.RLIMIT_CPU,(300,300))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))

from app.adapters import research_report_docx, research_report_render, research_results_xlsx
from app.domain.research_results import report_package
from app.domain.statistics_reader_reports.render import renderer_identity
from app.domain.statistics_reader_reports import render_labels


def main():
    fixed=renderer_identity();mapping=render_labels.labels()
    render_labels.install(research_report_docx,mapping,research_results_xlsx)
    research_report_render.renderer_identity=lambda:fixed
    original_package=report_package.make_package
    def make_package(files,identity):
        files=dict(files)
        files['rebuild_support/statistics_labels.py']=Path(render_labels.__file__).read_bytes()
        files['rebuild_support/statistics_labels.json']=json.dumps(mapping,ensure_ascii=False,sort_keys=True).encode('utf-8')
        setup=b'''import json as _statistics_json
from pathlib import Path as _StatisticsPath
from rebuild_support import research_report_docx as _statistics_document
from rebuild_support import research_results_xlsx as _statistics_workbook
from rebuild_support.statistics_labels import install as _install_statistics_labels
_install_statistics_labels(_statistics_document, _statistics_json.loads((_StatisticsPath(__file__).resolve().parent/'rebuild_support/statistics_labels.json').read_text(encoding='utf-8')), _statistics_workbook)
'''
        files['rebuild_report.py']=setup+files['rebuild_report.py']
        return original_package(files,{**identity,'renderer_identity':fixed})
    report_package.make_package=make_package
    data=json.loads(sys.stdin.buffer.read(8*1024**2))
    try:
        result=research_report_render.render_report(data['payload'],data['output'],enforce_deadlines=True)
    except ValueError as exc:
        if 'limit exceeded' not in str(exc):raise
        result={'error':'research_export_limit_exceeded'}
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
