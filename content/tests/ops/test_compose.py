"""The compose file every role of the platform runs from (W1-11), read as an operator relies on it: each long-running
role restarts after anything but a deliberate stop, gets SIGTERM through an init, is health-checked (the roles without
HTTP by the heartbeat their loop touches), names itself to Postgres, and runs the one image built once; site jobs have
a queue of their own that the worker consumes."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from django.conf import settings

COMPOSE = Path(settings.REPO_ROOT) / "docker-compose.yml"
HEARTBEAT_ROLES = {
    "beat": "beat",
    "relay": "relay",
    "belt-publisher": "consumer-outboxdesk-1",
    "events": "consumer-platform-1",
}


@pytest.fixture(scope="module")
def services() -> dict:
    return yaml.safe_load(COMPOSE.read_text())["services"]


@pytest.fixture(scope="module")
def platform(services) -> dict:
    return {name: s for name, s in services.items() if "content" in s.get("profiles", [])}


def command(service: dict) -> str:
    value = service["command"]
    return " ".join(value) if isinstance(value, list) else value


def test_every_platform_role_restarts_runs_under_an_init_and_is_health_checked(platform):
    assert {"db", "redis", "content", "worker", "research-worker", "beat", "relay", "belt-publisher", "events"} <= set(
        platform
    )
    for name, service in platform.items():
        assert service.get("init") is True, f"{name}: PID 1 must be an init that forwards SIGTERM and reaps"
        assert service.get("restart") == "unless-stopped", name
        check = service.get("healthcheck") or {}
        assert check.get("test") and not check.get("disable"), f"{name} has no healthcheck"


def test_the_web_role_execs_gunicorn_so_sigterm_reaches_it(platform):
    # The last step of the shell's script replaces it, so tini's child is gunicorn itself.
    assert re.search(r'&&\s*exec gunicorn config\.wsgi:application"$', command(platform["content"]))


def test_the_roles_that_drain_get_time_to_finish(platform):
    for name in ("worker", "research-worker"):
        assert platform[name]["stop_grace_period"] == "60s", name


def test_the_roles_without_http_are_checked_by_the_heartbeat_their_loop_touches(platform):
    for name, beat in HEARTBEAT_ROLES.items():
        test = platform[name]["healthcheck"]["test"]
        assert test[:4] == ["CMD", "python", "-m", "ops.heartbeat"] and test[4] == beat, name
        assert float(test[5]) > 0
    assert "--name outboxdesk-1" in command(platform["belt-publisher"])
    assert "--name platform-1" in command(platform["events"])
    assert "--scheduler ops.beat.HeartbeatScheduler" in command(platform["beat"])


def test_one_image_is_built_once_and_every_role_runs_it(platform):
    image = platform["content"]["image"]
    assert image.startswith("zer0-cms-content:") and platform["content"]["build"]["dockerfile"] == "content/Dockerfile"
    for name, service in platform.items():
        if name in ("db", "redis"):
            continue
        assert service["image"] == image, name
        if name != "content":
            assert "build" not in service, f"{name} builds its own copy"
            assert service["pull_policy"] == "never", f"{name} would look for {image} in a registry"


def test_every_celery_role_mounts_the_media_volume(platform):
    for name in ("worker", "research-worker"):
        assert "content-media:/app/content/media" in platform[name]["volumes"], name


def test_site_jobs_run_on_their_own_queue_which_the_worker_consumes(platform):
    assert settings.CELERY_TASK_ROUTES["jobs.tasks.run_job"] == {"queue": "sites"}
    queues = re.search(r"-Q (\S+)", command(platform["worker"])).group(1).split(",")
    assert queues == ["celery", "sites"]
    assert "sites" not in re.search(r"-Q (\S+)", command(platform["research-worker"])).group(1).split(",")


def test_every_role_names_itself_to_postgres(platform):
    names = {}
    for name, service in platform.items():
        if name in ("db", "redis"):
            continue
        names[name] = service["environment"].get("DATABASE_APPLICATION_NAME", settings.APP_NAME)
    assert len(set(names.values())) == len(names), names


def test_postgres_logs_who_connects_and_which_backend_said_what(platform):
    flags = command(platform["db"])
    assert "log_connections=on" in flags and "log_disconnections=on" in flags
    prefix = re.search(r"log_line_prefix=(.*?%a.*)", flags)
    assert prefix and "%p" in prefix.group(1)


def test_the_application_name_reaches_the_postgres_connection():
    """As compose sets it: production settings, a Postgres URL and the role's name; nothing connects."""
    probe = "from django.conf import settings; print(settings.DATABASES['default']['OPTIONS']['application_name'])"
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "SECRET_KEY": "test-only",
        "DATABASE_URL": "postgres://zer0:zer0@db:5432/zer0",
        "DATABASE_APPLICATION_NAME": "zer0-relay",
    }
    run = subprocess.run(
        [sys.executable, "-c", f"import django; django.setup(); {probe}"],
        cwd=settings.BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "zer0-relay"
    del env["DATABASE_APPLICATION_NAME"]
    unnamed = subprocess.run(
        [sys.executable, "-c", f"import django; django.setup(); {probe}"],
        cwd=settings.BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    assert unnamed.stdout.strip() == settings.APP_NAME, unnamed.stderr
