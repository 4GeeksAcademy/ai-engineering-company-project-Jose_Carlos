"""TrackedTask con un worker real: reintentos con backoff, DLQ y logs (hito 22)."""

import logging
import re
import uuid

import pytest

from services.tasks import base, dead_letters
from tests.tasks.conftest import wait_for
from tests.tasks.sample_tasks import ATTEMPTS, always_fails, bad_input, flaky

pytestmark = pytest.mark.usefixtures("celery_worker")


def new_key() -> str:
    return uuid.uuid4().hex


def test_a_task_that_works_first_time_succeeds_without_retries(dlq_db):
    key = new_key()
    result = flaky.delay(key, 0)
    assert wait_for(result) == "SUCCESS"
    assert result.result == {"key": key, "attempts": 1}
    assert dead_letters.list_dead_letters(dlq_db) == []


def test_a_transient_failure_is_retried_until_it_works(dlq_db):
    key = new_key()
    result = flaky.delay(key, 2)  # falla 2 veces, la tercera funciona
    assert wait_for(result) == "SUCCESS"
    assert result.result["attempts"] == 3
    assert result.retries == 2
    assert dead_letters.list_dead_letters(dlq_db) == []  # se recuperó: no va a la DLQ


def test_retries_wait_an_exponential_backoff_never_immediately(dlq_db):
    key = new_key()
    assert wait_for(always_fails.delay(key)) == "FAILURE"
    times = ATTEMPTS[key]
    gaps = [later - earlier for earlier, later in zip(times, times[1:])]
    backoff = base.retry_backoff_seconds()  # 0.05 s en los tests (10 s por defecto)
    assert len(gaps) == 3
    for retry, gap in enumerate(gaps):
        assert gap >= backoff * 2**retry * 0.9, f"el reintento {retry + 1} llegó a los {gap:.3f} s"
    assert gaps[0] < gaps[1] < gaps[2]


def test_the_backoff_is_10_20_40_seconds_by_default(monkeypatch):
    monkeypatch.delenv(base.RETRY_BACKOFF_ENV)
    task = always_fails
    assert [task.backoff_countdown(retries) for retries in range(3)] == [10, 20, 40]
    assert task.max_retries == 3


def test_after_three_retries_the_task_lands_in_the_dead_letter_queue(dlq_db):
    key = new_key()
    result = always_fails.delay(key)
    assert wait_for(result) == "FAILURE"
    assert len(ATTEMPTS[key]) == 4  # 1 intento + max_retries=3 reintentos

    letter = dead_letters.get_dead_letter(dlq_db, result.id)
    assert letter is not None
    assert letter["task_name"] == "tests.always_fails"
    assert letter["attempt"] == 4
    assert letter["max_retries"] == 3
    assert letter["error_type"] == "Boom"
    assert "fallo permanente, intento 4" in letter["error_message"]
    assert "Traceback" in letter["error_message"]  # el error completo, no solo el mensaje
    assert letter["args"] == [key]
    assert letter["failed_at"] is not None
    assert dead_letters.list_dead_letters(dlq_db) and len(dead_letters.list_dead_letters(dlq_db)) == 1


def test_a_non_retryable_error_goes_straight_to_the_dead_letter_queue(dlq_db):
    key = new_key()
    result = bad_input.delay(key)
    assert wait_for(result) == "FAILURE"
    assert len(ATTEMPTS[key]) == 1
    assert dead_letters.get_dead_letter(dlq_db, result.id)["attempt"] == 1


def test_the_dead_letter_queue_keeps_one_row_per_task(dlq_db):
    task_id = str(uuid.uuid4())
    kwargs = dict(task_id=task_id, task_name="x", attempt=4, max_retries=3, error=RuntimeError("e"), error_message="e")
    assert dead_letters.record_dead_letter(dlq_db, **kwargs) is True
    assert dead_letters.record_dead_letter(dlq_db, **kwargs) is False
    assert len(dead_letters.list_dead_letters(dlq_db)) == 1


def test_if_the_database_is_down_the_dead_letter_still_reaches_the_log(monkeypatch, caplog):
    def down():
        raise ConnectionError("base caída")

    monkeypatch.setattr(dead_letters, "dead_letter_engine", down)
    key = new_key()
    with caplog.at_level(logging.INFO, logger="services.tasks"):
        result = bad_input.delay(key)
        assert wait_for(result) == "FAILURE"
    assert any("status=dead_letter_unrecorded" in r.getMessage() and result.id in r.getMessage()
               for r in caplog.records)


LINE = re.compile(r"task=(?P<task>\S+) task_id=(?P<id>\S+) attempt=(?P<attempt>\d+/\d+) status=(?P<status>\w+)"
                  r"(?: duration_ms=(?P<ms>\d+))?")


def test_every_attempt_logs_task_id_attempt_status_and_duration(dlq_db, caplog):
    key = new_key()
    with caplog.at_level(logging.INFO, logger="services.tasks"):
        result = flaky.delay(key, 1)
        assert wait_for(result) == "SUCCESS"
    lines = [m.groupdict() for r in caplog.records if r.name == "services.tasks"
             if (m := LINE.search(r.getMessage())) and m["id"] == result.id]
    assert [(line["attempt"], line["status"]) for line in lines] == [
        ("1/4", "started"), ("1/4", "retry"), ("2/4", "started"), ("2/4", "success"),
    ]
    assert all(line["ms"] is not None for line in lines if line["status"] != "started")


def test_failures_log_the_full_error_message(dlq_db, caplog):
    key = new_key()
    with caplog.at_level(logging.INFO, logger="services.tasks"):
        result = always_fails.delay(key)
        assert wait_for(result) == "FAILURE"
    failures = [r for r in caplog.records if result.id in r.getMessage() and "status=failure" in r.getMessage()]
    assert len(failures) == 1 and failures[0].levelno == logging.ERROR
    message = failures[0].getMessage()
    assert "attempt=4/4" in message and "Boom: fallo permanente, intento 4" in message and "Traceback" in message
    retries = [r for r in caplog.records if result.id in r.getMessage() and "status=retry" in r.getMessage()]
    assert len(retries) == 3 and all("Boom" in r.getMessage() for r in retries)


def test_calling_a_task_directly_runs_it_without_the_queue():
    key = new_key()
    assert flaky(key, 0) == {"key": key, "attempts": 1}


def test_a_brief_database_outage_does_not_lose_the_dead_letter(dlq_db, monkeypatch):
    real = dead_letters.record_dead_letter
    calls = []

    def flaky_record(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise ConnectionError("corte de un instante")
        return real(*args, **kwargs)

    monkeypatch.setattr(dead_letters, "record_dead_letter", flaky_record)
    monkeypatch.setattr(base, "DLQ_WRITE_PAUSE_SECONDS", 0.01)
    result = bad_input.delay(new_key())
    assert wait_for(result) == "FAILURE"
    assert len(calls) == 2
    assert dead_letters.get_dead_letter(dlq_db, result.id) is not None
