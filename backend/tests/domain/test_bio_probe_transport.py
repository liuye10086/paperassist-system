import sys
import pytest


@pytest.fixture(autouse=True)
def postgres_schema():yield None


def test_probe_rejects_science_rss_over_budget_before_success(tmp_path):
    from app.adapters.bio_insights_engine.probe_transport import monitored_run
    marker=tmp_path/'should-not-exist'
    code='import time,pathlib;time.sleep(10);pathlib.Path('+repr(str(marker))+').write_text("completed")'
    with pytest.raises(RuntimeError,match='science_rss_limit'):
        monitored_run([sys.executable,'-c',code],b'',timeout=15,rss_reader=lambda _:2*1024**3+1)
    assert not marker.exists()


def test_probe_normal_completion_and_timeout_are_distinct():
    from app.adapters.bio_insights_engine.probe_transport import monitored_run
    result=monitored_run([sys.executable,'-c','print("ready")'],b'',timeout=5,rss_reader=lambda _:1024)
    assert result.returncode==0 and result.stdout.strip()==b'ready'
    with pytest.raises(RuntimeError,match='science_wall_timeout'):
        monitored_run([sys.executable,'-c','import time;time.sleep(10)'],b'',timeout=.05,rss_reader=lambda _:1024)


def test_quantitative_gate_requires_both_actual_new_checks(tmp_path,monkeypatch):
    import json
    from app.domain.bio_insights import settings
    identity=dict(available=True,code_digest='a'*64)
    monkeypatch.setattr(settings,'runtime_identity',lambda:identity)
    path=tmp_path/'gate.json';monkeypatch.setenv(settings.RUNTIME_MANIFEST_ENV,str(path))
    path.write_text(json.dumps(dict(checks={'quantitative_continuous':True})))
    assert settings.quantitative_runtime_identity()['available'] is False
    path.write_text(json.dumps(dict(checks={'quantitative_continuous':True,'quantitative_counts':True})))
    assert settings.quantitative_runtime_identity()==identity
