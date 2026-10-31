"""Secret-free bounded local raster worker, invoked only by the parent adapter."""
import json
from pathlib import Path
import resource
import sys

resource.setrlimit(resource.RLIMIT_AS,(2*1024**3,2*1024**3))
resource.setrlimit(resource.RLIMIT_CPU,(55,55))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app.adapters.research_figure_render import render_figure

if __name__=='__main__':
    data=json.loads(sys.stdin.buffer.read(4*1024**2))
    print(json.dumps(render_figure(data['payload'],data['output']),ensure_ascii=False))
