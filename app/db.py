import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS licitaciones (
    nid_proceso      TEXT PRIMARY KEY,   -- id interno de SEACE de la convocatoria (la nomenclatura puede repetirse)
    nomenclatura     TEXT,
    entidad          TEXT,
    fecha_publicacion TEXT,          -- ISO yyyy-mm-dd HH:MM
    objeto           TEXT,
    descripcion      TEXT,
    valor_referencial REAL,
    moneda           TEXT,
    version_seace    TEXT,
    nid_convocatoria TEXT,
    anio             INTEGER,
    ruc              TEXT,
    palabras         TEXT,           -- palabras clave que la encontraron
    relevante        INTEGER DEFAULT 1,
    estado_seg       TEXT DEFAULT 'nueva',   -- nueva | interesante | descartada | postulada
    nota             TEXT,
    ficha_ok         INTEGER DEFAULT 0,
    ficha_json       TEXT,
    cierre_propuestas TEXT,          -- fin de "Presentacion de propuestas"
    first_seen       TEXT,
    last_seen        TEXT
);
CREATE TABLE IF NOT EXISTS cronograma (
    nid_proceso TEXT, etapa TEXT, inicio TEXT, fin TEXT
);
CREATE INDEX IF NOT EXISTS ix_cron ON cronograma(nid_proceso);
CREATE TABLE IF NOT EXISTS documentos (
    nid_proceso TEXT, etapa TEXT, documento TEXT, archivo_uuid TEXT,
    filename TEXT, tamano TEXT, fecha TEXT, local_path TEXT
);
CREATE INDEX IF NOT EXISTS ix_docs ON documentos(nid_proceso);
CREATE TABLE IF NOT EXISTS corridas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio TEXT, fin TEXT, palabra TEXT, anio INTEGER,
    encontradas INTEGER DEFAULT 0, nuevas INTEGER DEFAULT 0,
    estado TEXT, error TEXT
);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def conn():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)
    reclasificar()


def parse_fecha(s: str | None) -> str | None:
    """'30/09/2026 11:17' -> '2026-09-30 11:17' (acepta solo fecha tambien)."""
    if not s:
        return None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})(?:\s+(\d{2}):(\d{2}))?", s)
    if not m:
        return None
    d, mo, y, h, mi = m.groups()
    return f"{y}-{mo}-{d} {h or '00'}:{mi or '00'}"


def parse_monto(s: str | None) -> float | None:
    if not s:
        return None
    s = re.sub(r"[^\d.,]", "", s)
    if not s:
        return None
    return float(s.replace(",", ""))


def es_relevante(descripcion: str | None) -> int:
    d = descripcion or ""
    if not re.search(config.RELEVANTE_RE, d, re.I):
        # sin palabra fuerte: solo sirve un "multifuncional" claramente de oficina
        if not (re.search("multifuncional", d, re.I) and re.search(config.MULTIF_RE, d, re.I)
                and not re.search(config.NO_MULTIF_RE, d, re.I)):
            return 0
    # Si menciona alquiler/arrendamiento de equipos, se conserva aunque hable de mantenimiento/toner incluidos
    if re.search(r"(alquiler|arrendamiento|arriendo|locaci)", d, re.I):
        return 1
    return 0 if re.search(config.EXCLUIR_RE, d, re.I) else 1


def reclasificar():
    with conn() as c:
        for r in c.execute("SELECT nid_proceso, descripcion FROM licitaciones").fetchall():
            c.execute("UPDATE licitaciones SET relevante=? WHERE nid_proceso=?",
                      (es_relevante(r["descripcion"]), r["nid_proceso"]))


def upsert_licitacion(c: sqlite3.Connection, row: dict, palabra: str) -> bool:
    """Inserta o actualiza. Devuelve True si es nueva."""
    existing = c.execute(
        "SELECT palabras FROM licitaciones WHERE nid_proceso=?", (row["nid_proceso"],)
    ).fetchone()
    relevante = es_relevante(row["descripcion"])
    if existing:
        palabras = set(filter(None, (existing["palabras"] or "").split(",")))
        palabras.add(palabra)
        c.execute(
            "UPDATE licitaciones SET last_seen=?, palabras=?, valor_referencial=COALESCE(?,valor_referencial) "
            "WHERE nid_proceso=?",
            (now(), ",".join(sorted(palabras)), row["valor_referencial"], row["nid_proceso"]),
        )
        return False
    c.execute(
        """INSERT INTO licitaciones (nid_proceso, nomenclatura, entidad, fecha_publicacion, objeto, descripcion,
           valor_referencial, moneda, version_seace, nid_convocatoria, anio, palabras,
           relevante, first_seen, last_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["nid_proceso"], row["nomenclatura"], row["entidad"], row["fecha_publicacion"], row["objeto"],
            row["descripcion"], row["valor_referencial"], row["moneda"], row["version_seace"],
            row["nid_convocatoria"], row["anio"], palabra, relevante, now(), now(),
        ),
    )
    return True
