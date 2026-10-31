"""Compatibility entry; export uses the complete app resource, never this shim."""
from pathlib import Path
from runpy import run_path

_implementation=Path(__file__).resolve().parents[1]/'backend/app/reproduction_assets/bio_insights/render_worker.py'
if __name__=='__main__':
    run_path(str(_implementation),run_name='__main__')
else:
    globals().update(run_path(str(_implementation),run_name=__name__))
