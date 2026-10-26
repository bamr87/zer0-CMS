"""gunicorn's settings for the platform's web role.

gunicorn reads `gunicorn.conf.py` from its working directory, so the image's
CMD and the compose `content` service (both in content/) share this file.

Threaded workers, because a run's event stream (/api/v2/agent-runs/<id>/stream/,
which the studio's run timeline follows) holds its request for up to five
minutes. A sync worker gives a whole worker to it and sends no heartbeat while
it streams, so gunicorn kills it at `timeout` (30 s) and the browser gets a
broken stream; a gthread worker gives it one thread and keeps its heartbeat.
`WEB_CONCURRENCY` sets the worker count, as for any gunicorn.
"""

import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
worker_class = "gthread"
threads = 8
