"""Clase base de las tareas de TrackFlow: reintentos con backoff, logs y Dead Letter Queue.

Toda tarea se declara con `base=TrackedTask`:

    @app.task(bind=True, base=TrackedTask, name="...")
    def mi_tarea(self, some_id: str) -> dict: ...

y hereda, sin escribir nada más:

- **Reintentos con backoff exponencial**: cualquier excepción (salvo las de `dont_retry_on`) se
  reintenta hasta `max_retries = 3` veces, esperando `retry_backoff_seconds * 2**reintento`:
  10 s, 20 s y 40 s por defecto. Nunca se reintenta al instante.
- **Dead Letter Queue**: si el último intento también falla (o el error no se reintenta), la
  tarea se registra en `task_dead_letters` con `task_id`, intento, error completo y timestamp.
- **Logs**: cada intento escribe una línea al empezar y otra al terminar con `task_id`, intento,
  estado resultante y duración. Los fallos llevan además el traceback completo.

    task=reporting.run_weekly_performance_pipeline task_id=… attempt=2/4 status=retry duration_ms=… error=…

`attempt` cuenta ejecuciones: el primer intento es 1 y, con `max_retries = 3`, el último es 4.
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

from celery import Task
from celery.exceptions import Retry, SoftTimeLimitExceeded

from services.tasks import dead_letters

logger = logging.getLogger("services.tasks")

MAX_RETRIES = 3
RETRY_BACKOFF_ENV = "CELERY_RETRY_BACKOFF_SECONDS"
DEFAULT_RETRY_BACKOFF_SECONDS = 10.0


def retry_backoff_seconds() -> float:
    value = os.getenv(RETRY_BACKOFF_ENV, "").strip()
    return float(value) if value else DEFAULT_RETRY_BACKOFF_SECONDS


class TrackedTask(Task):
    """Base de las tareas: reintenta con backoff, registra cada intento y manda a la DLQ."""

    max_retries = MAX_RETRIES
    # Errores que fallarían igual en cada intento: van directos a la DLQ. El timeout (soft time
    # limit) también: una tarea que ya tardó 30 minutos tardaría lo mismo en el siguiente.
    dont_retry_on: tuple[type[BaseException], ...] = (SoftTimeLimitExceeded,)
    # Inicio de cada ejecución en este proceso, para medir la duración (un worker prefork ejecuta
    # una tarea a la vez por proceso; con `solo`, también).
    _started: dict[str, float] = {}

    # ---------------------------------------------------------------- reintentos

    def backoff_countdown(self, retries: int | None = None) -> float:
        """Espera antes del siguiente intento: base * 2**reintentos hechos (10, 20, 40 s)."""
        done = self.request.retries if retries is None else retries
        return retry_backoff_seconds() * (2 ** done)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        if self.request.called_directly:  # llamada normal de Python (tests, scripts): sin cola
            return super().__call__(*args, **kwargs)
        task_id = self.request.id
        self._started[task_id] = time.monotonic()
        logger.info("task=%s task_id=%s attempt=%s status=started", self.name, task_id, self._attempt())
        try:
            return super().__call__(*args, **kwargs)
        except Retry:
            raise
        except self.dont_retry_on:
            raise
        except Exception as error:  # noqa: BLE001 - cualquier otro fallo se reintenta
            # Con los reintentos agotados, Celery vuelve a lanzar `error`: entra en on_failure.
            raise self.retry(exc=error, countdown=self.backoff_countdown())

    # ---------------------------------------------------------------- resultado de cada intento

    def _attempt(self, request: Any = None) -> str:
        request = request or self.request
        return f"{(request.retries or 0) + 1}/{(self.max_retries or 0) + 1}"

    def _duration_ms(self, task_id: str) -> str:
        started = self._started.pop(task_id, None)
        return f"{(time.monotonic() - started) * 1000:.0f}" if started is not None else "?"

    def on_success(self, retval: Any, task_id: str, args: tuple, kwargs: dict) -> None:
        logger.info("task=%s task_id=%s attempt=%s status=success duration_ms=%s",
                    self.name, task_id, self._attempt(), self._duration_ms(task_id))

    def on_retry(self, exc: BaseException, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        # `self.request.retries` aún es el del intento que acaba de fallar.
        logger.warning(
            "task=%s task_id=%s attempt=%s status=retry duration_ms=%s next_retry_in_s=%.0f error=%s: %s\n%s",
            self.name, task_id, self._attempt(), self._duration_ms(task_id),
            self.backoff_countdown(), type(exc).__name__, exc, einfo.traceback if einfo else "",
        )

    def on_failure(self, exc: BaseException, task_id: str, args: tuple, kwargs: dict, einfo: Any) -> None:
        request = self.request
        attempt = (request.retries or 0) + 1
        traceback = einfo.traceback if einfo else f"{type(exc).__name__}: {exc}"
        logger.error(
            "task=%s task_id=%s attempt=%s status=failure duration_ms=%s error=%s: %s\n%s",
            self.name, task_id, self._attempt(), self._duration_ms(task_id), type(exc).__name__, exc, traceback,
        )
        self.send_to_dead_letter_queue(exc, task_id, args, kwargs, attempt=attempt, error_message=traceback)

    # ---------------------------------------------------------------- DLQ

    def send_to_dead_letter_queue(
        self, exc: BaseException, task_id: str, args: tuple, kwargs: dict, *, attempt: int, error_message: str,
    ) -> None:
        delivery = getattr(self.request, "delivery_info", None) or {}
        try:
            recorded = dead_letters.record_dead_letter(
                dead_letters.dead_letter_engine(),
                task_id=task_id,
                task_name=self.name,
                attempt=attempt,
                max_retries=self.max_retries,
                error=exc,
                error_message=error_message,
                args=args,
                kwargs=kwargs,
                queue=delivery.get("routing_key"),
                worker=getattr(self.request, "hostname", None),
                failed_at=datetime.now(timezone.utc),
            )
        except Exception as error:  # noqa: BLE001 - la DLQ no puede tumbar al worker
            # La base no responde: el fallo queda al menos en el log, con todo lo que iría en la fila.
            logger.critical(
                "task=%s task_id=%s attempt=%s status=dead_letter_unrecorded db_error=%s: %s args=%s kwargs=%s",
                self.name, task_id, attempt, type(error).__name__, error, args, kwargs,
            )
            return
        logger.error("task=%s task_id=%s attempt=%s status=dead_letter %s",
                     self.name, task_id, attempt, "registrada en task_dead_letters" if recorded else "ya estaba en la DLQ")
