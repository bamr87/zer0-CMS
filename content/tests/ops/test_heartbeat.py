"""The heartbeat probe a role without HTTP is health-checked by (W1-10): healthy while its loop's last pass is recent,
unhealthy when it is stale or never happened, and cheap — it never boots Django."""

import os
import subprocess
import sys
import time

from django.conf import settings

from ops import heartbeat


def test_a_fresh_heartbeat_is_healthy_and_a_stale_or_missing_one_is_not(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HEARTBEAT_DIR", str(tmp_path))
    assert heartbeat.main(["relay", "60"]) == 1
    assert "no heartbeat" in capsys.readouterr().out
    heartbeat.touch("relay")
    assert heartbeat.main(["relay", "60"]) == 0
    old = time.time() - 120
    os.utime(heartbeat.path("relay"), (old, old))
    assert heartbeat.main(["relay", "60"]) == 1
    assert "last pass 120 s ago" in capsys.readouterr().out


def test_an_unwritable_heartbeat_never_stops_the_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("HEARTBEAT_DIR", str(tmp_path / "missing"))
    heartbeat.touch("relay")  # logged, not raised
    assert heartbeat.age("relay") is None


def test_the_probe_runs_without_django(tmp_path):
    env = {**os.environ, "HEARTBEAT_DIR": str(tmp_path), "DJANGO_SETTINGS_MODULE": ""}
    probe = (
        "import sys, ops.heartbeat as h; h.touch('beat'); sys.exit(h.main(['beat', '60']) or 'django' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", probe], cwd=settings.BASE_DIR, env=env, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
