"""Manual-only Celery queue. Redis is transient; local artifacts are the result record."""

import os
from pathlib import Path
from urllib.parse import quote

from celery import Celery

from phase_b_shadow.runner import run_fixture

QUEUE = "phase_b_shadow_pdf"


def broker_url() -> str:
    password_path = Path(os.environ["PHASE_B_REDIS_PASSWORD_FILE"])
    password = password_path.read_text(encoding="utf-8").strip()
    if not password or len(password) < 24:
        raise RuntimeError("Redis password is absent or too short")
    return f"redis://:{quote(password, safe='')}@redis:6379/0"


app = Celery("jason_os_phase_b", broker=broker_url(), backend=None)
app.conf.update(task_serializer="json", accept_content=["json"], result_serializer="json",
                task_default_queue=QUEUE, task_routes={"phase_b_shadow.parse_pdf": {"queue": QUEUE}},
                worker_prefetch_multiplier=1, task_acks_late=True,
                task_reject_on_worker_lost=True, broker_connection_retry_on_startup=True,
                broker_transport_options={"visibility_timeout": 600},
                task_track_started=True, task_ignore_result=True,
                worker_max_tasks_per_child=1)


@app.task(name="phase_b_shadow.parse_pdf", bind=True, max_retries=2,
          soft_time_limit=150, time_limit=180)
def parse_pdf(self, fixture_id: str, source_sha256: str) -> dict:
    try:
        return run_fixture(fixture_id, source_sha256, Path(os.environ["PHASE_B_INPUT_DIR"]),
                           Path(os.environ["PHASE_B_OUTPUT_DIR"]), Path(os.environ["PHASE_B_MODEL_DIR"]))
    except OSError as exc:
        raise self.retry(exc=exc, countdown=min(30 * (2 ** self.request.retries), 120)) from exc
