"""The web role's server settings (content/gunicorn.conf.py) as gunicorn reads
them: threaded workers, so a run's event stream holds a thread and the worker
keeps its heartbeat. Under a sync worker gunicorn kills the stream at its
timeout (30 s) and the studio's run timeline never gets its `end` event."""

import runpy
from pathlib import Path

from gunicorn.config import Config

CONF = Path(__file__).resolve().parents[2] / "gunicorn.conf.py"


def test_gunicorn_serves_the_platform_on_threads():
    cfg = Config()
    for name, value in runpy.run_path(str(CONF)).items():
        if name in cfg.settings:
            cfg.set(name, value)
    assert cfg.worker_class_str == "gthread" and cfg.threads > 1
    assert cfg.bind == ["0.0.0.0:8000"]
