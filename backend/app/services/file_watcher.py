"""
Vigila carpetas (locales o montadas NFS/SMB) y crea jobs automáticamente
cuando aparece un nuevo PDF. Robusto ante desconexiones de red.
"""

import time
import threading
from pathlib import Path
from typing import Callable

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent
from loguru import logger


class PDFEventHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[str], None], stable_secs: float = 3.0):
        self._callback = callback
        self._stable_secs = stable_secs
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        # Thread que comprueba si los archivos dejaron de crecer
        self._checker = threading.Thread(target=self._stability_checker, daemon=True)
        self._checker.start()

    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(".pdf"):
            with self._lock:
                self._pending[event.src_path] = time.time()

    def on_moved(self, event):
        if not event.is_directory and event.dest_path.lower().endswith(".pdf"):
            with self._lock:
                self._pending[event.dest_path] = time.time()

    def _stability_checker(self):
        """Espera que el archivo deje de crecer antes de procesarlo."""
        while True:
            time.sleep(1.0)
            now = time.time()
            ready = []
            with self._lock:
                for path, last_seen in list(self._pending.items()):
                    if now - last_seen >= self._stable_secs:
                        p = Path(path)
                        try:
                            size_a = p.stat().st_size
                            time.sleep(0.5)
                            size_b = p.stat().st_size
                            if size_a == size_b and size_a > 0:
                                ready.append(path)
                                del self._pending[path]
                        except FileNotFoundError:
                            del self._pending[path]

            for path in ready:
                logger.info(f"Nuevo PDF detectado: {path}")
                try:
                    self._callback(path)
                except Exception as e:
                    logger.error(f"Error procesando nuevo archivo {path}: {e}")


class FileWatcher:
    def __init__(self, on_new_pdf: Callable[[str], None]):
        self._callback = on_new_pdf
        self._observers: dict[str, Observer] = {}
        self._running = False
        self._lock = threading.Lock()

    def watch(self, path: str):
        """Añade una ruta a vigilar. Puede llamarse múltiples veces."""
        p = Path(path)
        if not p.exists():
            logger.warning(f"Ruta de entrada no existe (se vigilará cuando aparezca): {path}")
            # Intentar crear si es local
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

        if path in self._observers:
            return

        handler = PDFEventHandler(callback=self._callback)
        observer = Observer()
        observer.schedule(handler, str(path), recursive=False)
        observer.start()

        with self._lock:
            self._observers[path] = observer

        self._running = True
        logger.info(f"Vigilando carpeta: {path}")

    def stop_all(self):
        with self._lock:
            for path, obs in self._observers.items():
                obs.stop()
                obs.join(timeout=5)
                logger.info(f"Detenida vigilancia de: {path}")
            self._observers.clear()
        self._running = False

    @property
    def watched_paths(self) -> list[str]:
        with self._lock:
            return list(self._observers.keys())

    @property
    def is_running(self) -> bool:
        return self._running
