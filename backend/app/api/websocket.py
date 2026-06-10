"""
WebSocket manager. Broadcast de eventos desde la API y desde el worker Celery
(vía Redis pub/sub para que los workers puedan notificar al frontend).
"""

import asyncio
import json
import redis as sync_redis
import threading
from typing import Any

from fastapi import WebSocket
from loguru import logger

from app.config import get_settings

settings = get_settings()

_CHANNEL = "ocr:events"


class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        logger.debug(f"WS conectado. Total: {len(self._connections)}")

    async def disconnect(self, ws: WebSocket):
        async with self._lock:
            if ws in self._connections:
                self._connections.remove(ws)
        logger.debug(f"WS desconectado. Total: {len(self._connections)}")

    async def broadcast(self, data: dict):
        msg = json.dumps(data)
        dead = []
        async with self._lock:
            connections = list(self._connections)

        for ws in connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)

        for ws in dead:
            await self.disconnect(ws)


manager = ConnectionManager()


# --- Broadcast sincrónico desde workers Celery vía Redis pub/sub ---

def broadcast_sync(data: dict):
    """Llamado desde Celery (contexto síncrono). Publica en Redis."""
    try:
        r = sync_redis.from_url(settings.redis_url, decode_responses=True)
        r.publish(_CHANNEL, json.dumps(data))
        r.close()
    except Exception as e:
        logger.error(f"Redis publish error: {e}")


def start_redis_listener(loop: asyncio.AbstractEventLoop):
    """
    Escucha el canal Redis en un thread y reenvia al WebSocket manager.
    Se inicia una sola vez al arrancar la aplicación FastAPI.
    """

    def _listen():
        try:
            r = sync_redis.from_url(settings.redis_url, decode_responses=True)
            pubsub = r.pubsub()
            pubsub.subscribe(_CHANNEL)
            logger.info(f"Redis listener activo en canal: {_CHANNEL}")

            for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        asyncio.run_coroutine_threadsafe(manager.broadcast(data), loop)
                    except Exception as e:
                        logger.error(f"Error procesando mensaje Redis: {e}")
        except Exception as e:
            logger.error(f"Redis listener error: {e}")

    t = threading.Thread(target=_listen, daemon=True)
    t.start()
    return t
