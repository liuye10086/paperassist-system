"""Exported figure-only child: no comparison, fitting or enrichment invocation."""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'code'))
import json
import codecs
import signal
import struct
import tempfile

from app.adapters.bio_insights_engine.worker import actual_identity,warm_render_environment,records
from app.adapters.bio_insights_engine.sandbox import enter
from app.adapters.bio_insights_engine.figures import run_figure
# iter_table loads this module lazily; preload trusted code before Landlock.
import app.adapters.bio_insights_engine.tables
from app.adapters.bio_engine.manifest import Writer,canonical
from app.domain.bio_insights.contracts import FigureConfig
from app.domain.bio_insights.settings import BioInsightsLimits


def main():
    sys.stdout.buffer.write(b'READY\n');sys.stdout.buffer.flush();pinned=[]
    try:
        header=sys.stdin.buffer.read(4)
        if len(header)!=4:raise ValueError('invalid_transport')
        size=struct.unpack('!I',header)[0]
        if not 0<size<=2097152:raise ValueError('input_transport_limit')
        body=sys.stdin.buffer.read(size)
        if len(body)!=size or sys.stdin.buffer.read(1):raise ValueError('invalid_transport')
        payload=json.loads(body);limits=BioInsightsLimits()
        if payload.get('kind')!='bio_insight_figure':raise ValueError('render_only_accepts_figures')
        FigureConfig.model_validate(payload['config'])
        signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(TimeoutError('render_deadline')))
        signal.alarm(limits.warmup_seconds)
        from PIL import Image
        Image.init();codecs.lookup('utf-8-sig')
        with tempfile.TemporaryDirectory(prefix='b04-render-warm-') as directory:warm_render_environment(Path(directory))
        actual=actual_identity()
        if actual!=payload['_runtime_identity'] or any(payload['identity'].get(k)!=actual[k] for k in ('engine_version','code_digest','environment_digest','lock_sha256')):
            raise RuntimeError('bio_insights_environment_unavailable')
        output=Path(payload['output_directory'])
        if output.is_symlink() or not output.is_dir() or any(output.iterdir()):raise ValueError('output_not_empty')
        files=records(payload);signal.alarm(limits.compute_wall_seconds);pinned=enter(files,output,int(sys.argv[1]))
        writer=Writer(output);writer.identity=payload['identity'];result=run_figure(payload,writer)
        writer.json('methods',result['methods'])
        # Plot data and methods fully specify this render; raw analysis recipe is
        # preserved separately in the immutable package, never rerun here.
        manifest=dict(schema_version=1,engine_version='bio_insights_v1.0.0',kind='bio_insight_figure',identity=payload['identity'],
            summary=result['summary'],methods=result['methods'],inference_scope='visualization',provenance='system_computed',
            render_only=True,analysis_recomputed=False,members=[{k:v for k,v in m.items() if k!='path'} for m in writer.artifacts])
        writer.json('manifest',manifest)
        answer={'result':dict(schema_version=1,status='completed',kind='bio_insight_figure',engine_version='bio_insights_v1.0.0',
            identity=payload['identity'],manifest=manifest,outputs=writer.artifacts,**result)}
    except Exception as exc:answer={'error':{'code':str(exc)[:200]}}
    finally:
        for descriptor in pinned:os.close(descriptor)
    content=canonical(answer)
    if len(content)>2097152:raise ValueError('output_transport_limit')
    sys.stdout.buffer.write(content);sys.stdout.buffer.flush()


if __name__=='__main__':main()
