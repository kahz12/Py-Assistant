"""
core/lane_queue.py -- Sistema de colas por "lane" inspirado en OpenClaw.

Garantiza procesamiento serial de mensajes por usuario (lane_id),
previniendo race conditions cuando hay mensajes en rafaga.

Arquitectura:
  - Cada lane_id (user_id de Telegram) tiene su propia asyncio.Queue.
  - Un worker coroutine procesa items de la cola uno a la vez, FIFO.
  - Si ya hay un worker activo en un lane, no se crea otro.
  - El callback (normalmente assistant.process + send_message) se ejecuta
    de forma serializada y segura.

Write-Ahead Queue (WAQ):
  - Cada item se serializa a disco en waq_dir antes de procesarse.
  - Al completarse correctamente, su archivo WAQ se elimina.
  - Al iniciar, se re-encolan items huerfanos para recuperacion tras crash.

Uso:
    queue = LaneQueue(waq_dir=Path("memory_vault/waq"))
    await queue.enqueue(lane_id, "Texto", callback_fn)
"""
import asyncio
import json
import uuid
import time
from pathlib import Path
from typing import Callable, Awaitable, Any, Optional
from loguru import logger


# ---------------------------------------------------------------------------
# Write-Ahead Queue Storage
# ---------------------------------------------------------------------------

class WAQStorage:
    """
    Capa de persistencia para el Write-Ahead Queue.

    Cada item pendiente se guarda como JSON en `waq_dir`.
    El nombre del archivo incluye el lane_id y un UUID unico para
    garantizar ordenamiento y recuperacion correcta tras un crash.

    Atributos:
        waq_dir: Directorio donde se persisten los items pendientes.
    """

    def __init__(self, waq_dir: Path):
        self.waq_dir = waq_dir
        self.waq_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"[WAQ] Storage inicializado en: {waq_dir}")

    def write(self, lane_id: str, payload: Any) -> str:
        """
        Persiste un item a disco antes de encolarlo.

        Args:
            lane_id: Identificador del lane.
            payload: Datos serializables (texto del mensaje).

        Returns:
            waq_id: ID unico del item (nombre del archivo sin extension).
        """
        waq_id = f"{lane_id}__{int(time.time() * 1000)}__{uuid.uuid4().hex[:8]}"
        item = {"waq_id": waq_id, "lane_id": lane_id, "payload": payload, "ts": time.time()}
        try:
            path = self.waq_dir / f"{waq_id}.json"
            path.write_text(json.dumps(item, ensure_ascii=False), encoding="utf-8")
            logger.debug(f"[WAQ] Item escrito: {waq_id}")
        except Exception as e:
            logger.warning(f"[WAQ] No se pudo persistir item: {e}")
        return waq_id

    def complete(self, waq_id: str) -> None:
        """Elimina el archivo WAQ de un item completado exitosamente."""
        path = self.waq_dir / f"{waq_id}.json"
        try:
            path.unlink(missing_ok=True)
            logger.debug(f"[WAQ] Item completado y eliminado: {waq_id}")
        except Exception as e:
            logger.warning(f"[WAQ] No se pudo eliminar item WAQ '{waq_id}': {e}")

    def load_orphans(self) -> list[dict]:
        """
        Carga items huerfanos (no completados antes del crash).

        Returns:
            Lista de items ordenados por timestamp, listos para re-encolar.
        """
        items = []
        for f in self.waq_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                items.append(data)
            except Exception as e:
                logger.warning(f"[WAQ] No se pudo leer item huerfano '{f.name}': {e}")
        items.sort(key=lambda x: x.get("ts", 0))
        if items:
            logger.info(f"[WAQ] {len(items)} item(s) huerfanos recuperados.")
        return items


# ---------------------------------------------------------------------------
# LaneQueue con WAQ integrado
# ---------------------------------------------------------------------------

class LaneQueue:
    """
    Cola de procesamiento serializado por lane con Write-Ahead Queue.

    Cada lane es identificado por un `lane_id` (user_id de Telegram).
    Los mensajes dentro de un mismo lane se procesan en orden estricto
    (FIFO) y se persisten a disco para sobrevivir a crashes del proceso.

    Atributos:
        _queues: Diccionario de asyncio.Queue, indexado por lane_id.
        _active: Set de lane_ids con worker activo.
        _waq: Capa WAQ (None si no se provee waq_dir).
        _waq_ids: Mapeo de (lane_id, payload) -> waq_id para cleanup.
    """

    def __init__(self, waq_dir: Optional[Path] = None):
        self._queues: dict[str, asyncio.Queue] = {}
        self._active: set[str] = set()
        self._waq: Optional[WAQStorage] = WAQStorage(waq_dir) if waq_dir else None
        logger.info(f"LaneQueue inicializado. WAQ: {'activado' if self._waq else 'desactivado'}")

    def _get_queue(self, lane_id: str) -> asyncio.Queue:
        """Obtiene o crea la queue para un lane dado."""
        if lane_id not in self._queues:
            self._queues[lane_id] = asyncio.Queue()
        return self._queues[lane_id]

    async def recover_orphans(self, callback_factory: Callable[[str], Callable]) -> int:
        """
        Re-encola items huerfanos recuperados del WAQ tras un crash.

        Debe llamarse una vez al iniciar, antes de arrancar el bot.

        Args:
            callback_factory: Funcion que, dado un lane_id, retorna el
                              callback apropiado para procesar ese lane.
                              (Tipicamente una closure con el bot de Telegram)

        Returns:
            Numero de items recuperados.
        """
        if not self._waq:
            return 0
        orphans = self._waq.load_orphans()
        for item in orphans:
            lane_id = item["lane_id"]
            payload = item["payload"]
            waq_id = item["waq_id"]
            callback = callback_factory(lane_id)
            # Wrap para limpiar el WAQ al completarse
            original_cb = callback
            async def _wrapped(p, _waq_id=waq_id, _cb=original_cb):
                await _cb(p)
                if self._waq:
                    self._waq.complete(_waq_id)
            queue = self._get_queue(lane_id)
            await queue.put((payload, _wrapped))
            if lane_id not in self._active:
                asyncio.create_task(self._worker(lane_id))
        return len(orphans)

    async def enqueue(
        self,
        lane_id: str,
        payload: Any,
        callback: Callable[[Any], Awaitable[Any]],
    ) -> None:
        """
        Añade un item a la cola del lane, lo persiste en WAQ, y arranca
        el worker si no esta activo.

        Args:
            lane_id: Identificador del lane (ej. str(user_id)).
            payload: Datos que se pasaran al callback (ej. texto del mensaje).
            callback: Funcion async a invocar con el payload.
        """
        # Persistir a disco ANTES de encolar (Write-Ahead)
        waq_id = self._waq.write(lane_id, payload) if self._waq else None

        # Wrap para limpiar el WAQ al completarse
        async def _waq_callback(p):
            try:
                await callback(p)
            finally:
                if waq_id and self._waq:
                    self._waq.complete(waq_id)

        queue = self._get_queue(lane_id)
        await queue.put((payload, _waq_callback))
        logger.debug(f"[Lane={lane_id}] Item encolado. Pendientes: {queue.qsize()}")

        if lane_id not in self._active:
            asyncio.create_task(self._worker(lane_id))

    async def _worker(self, lane_id: str) -> None:
        """
        Worker que procesa items de la cola de un lane de forma serializada.
        Se auto-termina cuando la cola esta vacia.
        """
        self._active.add(lane_id)
        queue = self._get_queue(lane_id)
        logger.debug(f"[Lane={lane_id}] Worker iniciado.")

        try:
            while not queue.empty():
                payload, callback = await queue.get()
                logger.debug(f"[Lane={lane_id}] Procesando item.")
                try:
                    await callback(payload)
                except Exception as e:
                    logger.error(f"[Lane={lane_id}] Error en callback: {e}")
                finally:
                    queue.task_done()
        finally:
            self._active.discard(lane_id)
            logger.debug(f"[Lane={lane_id}] Worker terminado.")

    def queue_size(self, lane_id: str) -> int:
        """Retorna el numero de items pendientes en un lane."""
        return self._queues.get(lane_id, asyncio.Queue()).qsize()

    def is_active(self, lane_id: str) -> bool:
        """Indica si existe un worker activo en el lane dado."""
        return lane_id in self._active

    def all_lanes_status(self) -> dict[str, dict]:
        """Retorna un resumen del estado de todos los lanes (para el dashboard)."""
        return {
            lane_id: {
                "pending": q.qsize(),
                "active": lane_id in self._active,
            }
            for lane_id, q in self._queues.items()
        }
