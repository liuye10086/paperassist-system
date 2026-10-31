"""Refresh runtime proof only from an actual isolated current-image probe."""
import json
from pathlib import Path
import subprocess
import time
import cr_b04_runner as control


def main():
    control.read_state();stamp=str(time.time_ns());directory=control.RUNTIME/'tasks'
    command=['docker','run','--rm','--network','none','--read-only','--memory','4g','--cpus','1','--pids-limit','64',
        '--tmpfs','/tmp:rw,size=1g','--entrypoint','/opt/paperassist-bio-insights/bin/python',control.WORKER_IMAGE,
        '-m','app.adapters.bio_insights_engine.runtime_probe']
    with (directory/('T09-probe-'+stamp+'.stdout.json')).open('wb') as out,(directory/('T09-probe-'+stamp+'.stderr.txt')).open('wb') as err:
        result=subprocess.run(command,cwd=control.ROOT,stdout=out,stderr=err,timeout=360)
    if result.returncode:raise RuntimeError('Actual runtime probe failed; retained '+stamp)
    report=json.loads((directory/('T09-probe-'+stamp+'.stdout.json')).read_bytes())
    if report.get('status')!='passed':raise ValueError('Probe did not pass')
    if control.GATE.exists():
        history=control.RUNTIME/'gate-history';history.mkdir(exist_ok=True)
        control.worker_stack.private_write(history/(stamp+'.json'),control.GATE.read_text(encoding='utf-8'))
    control.worker_stack.private_write(control.GATE,json.dumps(report,indent=2))
    control.configure(control.read_state());value=control.probe()
    if not value.get('available'):raise ValueError('Actual image proof does not match current host engine')
    print(json.dumps(dict(identity=value,peak_rss_kib=report['peak_rss_kib'],container_peak_memory_bytes=report['container_peak_memory_bytes'],receipt=stamp)))


if __name__=='__main__':main()
