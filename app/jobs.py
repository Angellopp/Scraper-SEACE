"""Ejecuta scrapeos en segundo plano (uno a la vez) y guarda un log consultable desde la web."""
import os
import threading
from collections import deque

from . import config, db, notify

_lock = threading.Lock()
estado = {"corriendo": False, "tarea": None, "inicio": None, "fin": None, "resultado": None}
logs: deque[str] = deque(maxlen=300)

HEADLESS = os.getenv("SEACE_HEADLESS", "0") == "1"


def log(msg: str):
    line = f"{db.now()}  {msg}"
    logs.append(line)
    print(line, flush=True)


def _lanzar(nombre: str, fn):
    if not _lock.acquire(blocking=False):
        return False

    def run():
        estado.update(corriendo=True, tarea=nombre, inicio=db.now(), fin=None, resultado=None)
        try:
            estado["resultado"] = fn()
        except Exception as e:  # noqa: BLE001
            log(f"ERROR en {nombre}: {e}")
            estado["resultado"] = {"error": str(e)}
        finally:
            estado.update(corriendo=False, fin=db.now())
            _lock.release()

    threading.Thread(target=run, daemon=True).start()
    return True


def scrapear(keywords=None, anios=None, refrescar=False, avisar=True) -> bool:
    from . import scraper

    def fn():
        t0 = db.now()
        log(f"Inicio de scrapeo (headless={HEADLESS})")
        res = scraper.correr(keywords, anios, headless=HEADLESS, refrescar=refrescar, log=log)
        with db.conn() as c:
            nuevas = [dict(r) for r in c.execute(
                "SELECT * FROM licitaciones WHERE first_seen >= ? AND relevante=1", (t0,))]
        log(f"Fin de scrapeo: {len(nuevas)} nuevas relevantes")
        if avisar:
            notify.enviar(nuevas, log=log)
        return {"corridas": res, "nuevas": len(nuevas)}

    return _lanzar("scrapeo", fn)


def descargar(nid_proceso: str) -> bool:
    from . import scraper

    def fn():
        log(f"Descargando documentos de {nid_proceso}")
        with scraper.Scraper(headless=HEADLESS, log=log) as s:
            files = s.descargar_docs(nid_proceso)
        log(f"{len(files)} archivos descargados")
        return {"archivos": files}

    return _lanzar("descarga", fn)
