"""Run transport in the real backend interpreter, not the science-only venv."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.adapters.bio_insights_process import execute_bio_insights
payload=json.load(sys.stdin)
result=execute_bio_insights(payload,payload['output_directory'])
print(json.dumps(result,allow_nan=False))
