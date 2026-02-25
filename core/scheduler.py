"""
core/scheduler.py -- Invocacion Autonoma inspirado en OpenClaw.

Permite registrar Jobs (cron, interval, one_shot) que se disparan
automaticamente sin intervencion del usuario para que ARIA actue
de forma proactiva.

Usa APScheduler con AsyncIOScheduler para compatibilidad total con
el event loop de python-telegram-bot (asyncio).

Uso:
    scheduler = AssistantScheduler()
    scheduler.register_cron(mi_func, hour=8, minute=0, id="morning_summary")
    scheduler.register_interval(mi_func, minutes=60, id="hourly_check")
    scheduler.start()
"""
from typing import Callable, Awaitable
from loguru import logger

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.date import DateTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False


class AssistantScheduler:
    """
    Wrapper liviano sobre APScheduler para gestionar invocaciones autonomas.

    Permite registrar funciones async que se ejecutan proactivamente
    mediante cron, intervalos repetitivos o disparos únicos (one-shot).

    Atributos:
        _scheduler: Instancia de AsyncIOScheduler de APScheduler.
        _started: Flag que indica si el scheduler está corriendo.
    """

    def __init__(self):
        if not APSCHEDULER_AVAILABLE:
            logger.warning(
                "APScheduler no está instalado. Autonomous Invocation desactivado. "
                "Instala con: pip install APScheduler>=3.10.4"
            )
            self._scheduler = None
        else:
            self._scheduler = AsyncIOScheduler()
        self._started = False
        logger.info("AssistantScheduler iniciado (Autonomous Invocation).")

    def register_cron(
        self,
        func: Callable[[], Awaitable],
        id: str,
        hour: int = None,
        minute: int = 0,
        day_of_week: str = "*",
        **kwargs,
    ) -> bool:
        """
        Registra un job de tipo CRON (ejecucion en hora/dia especificos).

        Args:
            func: Funcion async a ejecutar.
            id: Identificador único del job.
            hour: Hora de disparo (0-23).
            minute: Minuto de disparo (0-59).
            day_of_week: Dias de la semana ('mon,tue' o '*' para todos).
            **kwargs: Argumentos adicionales para APScheduler.

        Returns:
            True si el job fue registrado exitosamente.
        """
        if not self._scheduler:
            return False
        try:
            trigger = CronTrigger(
                hour=hour, minute=minute, day_of_week=day_of_week
            )
            self._scheduler.add_job(func, trigger=trigger, id=id, replace_existing=True, **kwargs)
            logger.info(f"[Scheduler] Job CRON '{id}' registrado (hora={hour}, min={minute}).")
            return True
        except Exception as e:
            logger.error(f"[Scheduler] Error al registrar cron '{id}': {e}")
            return False

    def register_interval(
        self,
        func: Callable[[], Awaitable],
        id: str,
        seconds: int = None,
        minutes: int = None,
        hours: int = None,
        **kwargs,
    ) -> bool:
        """
        Registra un job de tipo INTERVALO (repetición periódica).

        Args:
            func: Funcion async a ejecutar.
            id: Identificador único del job.
            seconds/minutes/hours: Intervalo de repetición.

        Returns:
            True si el job fue registrado exitosamente.
        """
        if not self._scheduler:
            return False
        try:
            trigger = IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours)
            self._scheduler.add_job(func, trigger=trigger, id=id, replace_existing=True, **kwargs)
            logger.info(f"[Scheduler] Job INTERVALO '{id}' registrado.")
            return True
        except Exception as e:
            logger.error(f"[Scheduler] Error al registrar interval '{id}': {e}")
            return False

    def register_one_shot(
        self,
        func: Callable[[], Awaitable],
        id: str,
        run_date: str,
        **kwargs,
    ) -> bool:
        """
        Registra un job de disparo unico (one-shot / recordatorio).

        Args:
            func: Funcion async a ejecutar.
            id: Identificador único del job.
            run_date: Fecha/hora de disparo ISO 8601 (ej: '2026-03-01 08:00:00').

        Returns:
            True si el job fue registrado exitosamente.
        """
        if not self._scheduler:
            return False
        try:
            trigger = DateTrigger(run_date=run_date)
            self._scheduler.add_job(func, trigger=trigger, id=id, replace_existing=True, **kwargs)
            logger.info(f"[Scheduler] Job ONE-SHOT '{id}' registrado para {run_date}.")
            return True
        except Exception as e:
            logger.error(f"[Scheduler] Error al registrar one-shot '{id}': {e}")
            return False

    def remove_job(self, job_id: str) -> bool:
        """Elimina un job del scheduler por su ID."""
        if not self._scheduler:
            return False
        try:
            self._scheduler.remove_job(job_id)
            logger.info(f"[Scheduler] Job '{job_id}' eliminado.")
            return True
        except Exception as e:
            logger.warning(f"[Scheduler] No se pudo eliminar job '{job_id}': {e}")
            return False

    def list_jobs(self) -> list[str]:
        """Retorna los IDs de todos los jobs registrados."""
        if not self._scheduler:
            return []
        return [job.id for job in self._scheduler.get_jobs()]

    def start(self):
        """Arranca el scheduler en background (dentro del event loop asyncio activo)."""
        if not self._scheduler or self._started:
            return
        self._scheduler.start()
        self._started = True
        logger.info(f"[Scheduler] Iniciado con {len(self.list_jobs())} jobs.")

    def shutdown(self, wait: bool = False):
        """Detiene el scheduler de forma limpia."""
        if self._scheduler and self._started:
            self._scheduler.shutdown(wait=wait)
            self._started = False
            logger.info("[Scheduler] Detenido.")
