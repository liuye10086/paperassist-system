"""Probe-only bounded subprocess transport with no Web/runtime dependencies."""
import subprocess
import time
from pathlib import Path
from threading import Thread


def tree_rss(pid):
    try:
        status=Path(f'/proc/{pid}/status').read_text()
        rss=next((int(line.split()[1])*1024 for line in status.splitlines() if line.startswith('VmRSS:')),0)
        children=Path(f'/proc/{pid}/task/{pid}/children').read_text().split()
        return rss+sum(tree_rss(int(child)) for child in children)
    except (FileNotFoundError,ProcessLookupError):return 0


def monitored_run(command,body,*,timeout,rss_reader=tree_rss,memory_bytes=2*1024**3):
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    result={};start=time.monotonic();peak=0
    def communicate():
        try:result['stdout'],result['stderr']=process.communicate(body)
        except BaseException as exc:result['exception']=exc
    reader=Thread(target=communicate,daemon=True);reader.start()
    reason=None
    try:
        while process.poll() is None:
            peak=max(peak,rss_reader(process.pid))
            if peak>memory_bytes:reason='science_rss_limit';break
            if time.monotonic()-start>timeout:reason='science_wall_timeout';break
            reader.join(.02)
    finally:
        if process.poll() is None:process.kill()
        process.wait();reader.join(5)
    if reader.is_alive():raise RuntimeError('science_transport_incomplete')
    if reason:raise RuntimeError(reason)
    if 'exception' in result:raise result['exception']
    return subprocess.CompletedProcess(command,process.returncode,result['stdout'],result['stderr'])
