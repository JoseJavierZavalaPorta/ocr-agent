"""
FastAPI app principal. Incluye:
- Lifespan: inicia file watcher, listener Redis WS y recupera jobs interrumpidos
- API REST bajo /api
- WebSocket en /ws
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import get_settings
from app.database import init_db, SessionLocal
from app.api.routes import router, set_watcher
from app.api.websocket import manager, start_redis_listener
from app.services.file_watcher import FileWatcher
from app.services.job_manager import job_manager
from app.tasks.ocr_tasks import process_job_task

settings = get_settings()
_watcher: FileWatcher | None = None


def _enqueue_new_pdf(file_path: str):
    """Callback del watcher: crea job y lo encola en Celery."""
    db = SessionLocal()
    try:
        job = job_manager.create_job(db, file_path)
        process_job_task.apply_async(args=[job.id], queue="ocr")
        logger.info(f"Job encolado automáticamente: {job.id} ({job.filename})")
    except Exception as e:
        logger.error(f"Error encolando {file_path}: {e}")
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _watcher

    # Inicializar BD
    init_db()
    logger.info("Base de datos inicializada")

    # Recuperar jobs interrumpidos
    db = SessionLocal()
    try:
        recovered = job_manager.recover_interrupted_jobs(db)
        for job_id in recovered:
            process_job_task.apply_async(args=[job_id], queue="ocr")
        if recovered:
            logger.info(f"Re-encolados {len(recovered)} jobs interrumpidos")
    finally:
        db.close()

    # Iniciar file watcher
    _watcher = FileWatcher(on_new_pdf=_enqueue_new_pdf)
    _watcher.watch(settings.input_path)
    set_watcher(_watcher)

    # Iniciar listener Redis → WebSocket
    loop = asyncio.get_event_loop()
    start_redis_listener(loop)
    logger.info("Sistema OCR Agent iniciado y listo")

    yield

    # Cleanup
    if _watcher:
        _watcher.stop_all()
    logger.info("Sistema OCR Agent detenido")


app = FastAPI(
    title="OCR Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # mantener conexión viva
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
