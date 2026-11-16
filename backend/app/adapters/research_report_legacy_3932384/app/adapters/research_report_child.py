"""Offline report process; no credentials, network clients or external retrieval."""
import json
from pathlib import Path
import resource
import sys

resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
resource.setrlimit(resource.RLIMIT_CPU,(300,300))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.adapters.research_report_render import render_report

if __name__=='__main__':
    data=json.loads(sys.stdin.buffer.read(8*1024**2))
    try:result=render_report(data['payload'],data['output'],enforce_deadlines=True)
    except ValueError as exc:
        if 'limit exceeded' not in str(exc):raise
        result={'error':'research_export_limit_exceeded'}
    print(json.dumps(result,ensure_ascii=False))
