"""Compatibility entry; the shipped app resource is the single implementation."""
from pathlib import Path
from runpy import run_path

_implementation=Path(__file__).resolve().parents[1]/'backend/app/reproduction_assets/bio_insights/reproduce.py'
if __name__=='__main__':
    run_path(str(_implementation),run_name='__main__')
else:
    globals().update(run_path(str(_implementation),run_name=__name__))
