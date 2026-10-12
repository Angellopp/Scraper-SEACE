"""Scraper de SEACE (buscador publico de procedimientos de seleccion).

El sitio es JSF/PrimeFaces con reCAPTCHA v3 invisible: el token lo genera el JavaScript de la
pagina, por eso se maneja un navegador real con Playwright (no se llama al endpoint directo).
"""
import json
import random
import re
import time
import urllib.request
from datetime import date

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from . import config, db

FORM = "tbBuscador:idFormBuscarProceso"


def sel(suffix: str) -> str:
    """Selector CSS para un id JSF (los ':' se escapan)."""
    return "#" + f"{FORM}:{suffix}".replace(":", r"\:")


def pausa(a: float | None = None, b: float | None = None):
    time.sleep(random.uniform(a or config.PAUSA_MIN, b or config.PAUSA_MAX))


JS_PARSE_ROWS = """
() => {
  const rows = [...document.querySelectorAll('[id="tbBuscador:idFormBuscarProceso:dtProcesos_data"] tr[data-ri]')];
  return rows.map(tr => {
    const td = [...tr.children].map(c => c.innerText.trim());
    const img = tr.querySelector('img[id$="grafichaSel"]');
    const oc = img && img.parentElement ? (img.parentElement.getAttribute('onclick') || '') : '';
    const g = k => { const m = oc.match(new RegExp("'" + k + "':'([^']*)'")); return m ? m[1] : ''; };
    return {ri: tr.getAttribute('data-ri'), cells: td, nid_proceso: g('nidProceso'),
            nid_convocatoria: g('nidConvocatoria')};
  });
}
"""

JS_FICHA = """
() => {
  const txt = e => (e ? e.innerText.trim() : '');
  const info = {};
  document.querySelectorAll('tr').forEach(tr => {
    const tds = [...tr.children].filter(c => c.tagName === 'TD');
    if (tds.length === 2) {
      const k = txt(tds[0]).replace(/:\\s*$/, '');
      if (k && k.length < 80 && txt(tds[0]).endsWith(':') && !(k in info)) info[k] = txt(tds[1]);
    }
  });
  const rowsOf = id => [...document.querySelectorAll('[id="' + id + '"] tbody tr')];
  const cronograma = rowsOf('tbFicha:dtCronograma').map(tr => [...tr.children].map(txt))
        .filter(r => r.length >= 3);
  const entidad = rowsOf('tbFicha:dtEntidadContrata').map(tr => [...tr.children].map(txt))[0] || [];
  const docs = rowsOf('tbFicha:dtDocumentos').map(tr => {
    const c = [...tr.children];
    const a = tr.querySelector('a[onclick*="descargaDocGeneral"]');
    const m = a ? a.getAttribute('onclick').match(/descargaDocGeneral\\('([^']*)','([^']*)','([^']*)'/) : null;
    return {etapa: txt(c[1]), documento: txt(c[2]), tamano: txt(c[3]), fecha: txt(c[4]),
            uuid: m ? m[1] : '', filename: m ? m[3] : ''};
  }).filter(d => d.documento);
  const pg = document.getElementById('tbFicha:dtDocumentos_paginator_bottom');
  const next = pg ? pg.querySelector('.ui-paginator-next') : null;
  return {info, cronograma, entidad, docs, hasNext: !!(next && !next.classList.contains('ui-state-disabled'))};
}
"""


class Scraper:
    def __init__(self, headless: bool = False, log=print):
        self.headless = headless
        self.log = log
        self._pw = None
        self.ctx = None
        self.page = None

    # ---- ciclo de vida -------------------------------------------------
    def __enter__(self):
        config.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        last = None
        # Se prefiere el Chrome/Edge instalado (mejor puntaje reCAPTCHA); Chromium de Playwright como respaldo.
        for channel in (config.BROWSER_CHANNEL, "msedge", None):
            try:
                self.ctx = self._pw.chromium.launch_persistent_context(
                    str(config.PROFILE_DIR),
                    channel=channel,
                    headless=self.headless,
                    viewport={"width": 1400, "height": 900},
                    locale="es-PE",
                    timezone_id="America/Lima",
                    args=["--disable-blink-features=AutomationControlled"],
                    accept_downloads=True,
                )
                break
            except Exception as e:  # noqa: BLE001
                last = e
        else:
            raise RuntimeError(f"No se pudo abrir ningun navegador: {last}")
        self.ctx.set_default_timeout(45000)
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        return self

    def __exit__(self, *exc):
        try:
            self.ctx.close()
        finally:
            self._pw.stop()

    # ---- busqueda ------------------------------------------------------
    def abrir_buscador(self):
        p = self.page
        p.goto(config.BUSCADOR_URL, wait_until="networkidle")
        p.get_by_text("Buscador de Procedimientos de Selección").first.click()
        p.wait_for_selector(sel("descripcionObjeto"), state="visible")
        pausa()

    def buscar(self, palabra: str, anio: int) -> int:
        """Ejecuta la busqueda. Devuelve el total de resultados."""
        p = self.page
        self.abrir_buscador()
        p.fill(sel("descripcionObjeto"), palabra)
        p.evaluate(
            """(a) => { const s = document.querySelector('[id$="anioConvocatoria_input"]');
                        s.value = String(a); s.dispatchEvent(new Event('change', {bubbles: true})); }""",
            anio,
        )
        pausa()
        def es_busqueda(r):
            try:
                d = (r.request.post_data_buffer or b"").decode("latin-1")
            except Exception:  # noqa: BLE001
                return False
            return (r.request.method == "POST" and "buscadorPublico.xhtml" in r.url
                    and "javax.faces.source=tbBuscador%3AidFormBuscarProceso%3AbtnBuscarSel" in d)

        try:
            with p.expect_response(es_busqueda, timeout=60000):
                p.click(sel("btnBuscarSelToken"))
            p.wait_for_function(
                """() => { const e = document.getElementById('tbBuscador:idFormBuscarProceso:dtProcesos_paginator_bottom');
                          return e && /Mostrando/.test(e.innerText); }""",
                timeout=30000,
            )
            time.sleep(1.0)
        except PWTimeout:
            self._debug("busqueda_sin_resultados")
            raise RuntimeError(
                "La busqueda no devolvio la tabla de resultados (posible puntaje bajo de reCAPTCHA v3 "
                "o cambio en el sitio). Ver data/debug/."
            )
        self._ir_primera_pagina()
        pag = p.inner_text(f'[id="{FORM}:dtProcesos_paginator_bottom"]')
        m = re.search(r"del total (\d+)", pag)
        return int(m.group(1)) if m else 0

    def _filas_pagina(self) -> list[dict]:
        out = []
        for r in self.page.evaluate(JS_PARSE_ROWS):
            c = r["cells"]
            if len(c) < 12:
                continue
            fecha = db.parse_fecha(c[2])
            out.append({
                "ri": r["ri"],
                "entidad": c[1],
                "fecha_publicacion": fecha,
                "nomenclatura": c[3],
                "objeto": c[5],
                "descripcion": c[6],
                "valor_referencial": db.parse_monto(c[9]),
                "moneda": c[10],
                "version_seace": c[11],
                "nid_proceso": r["nid_proceso"],
                "nid_convocatoria": r["nid_convocatoria"],
                "anio": int(fecha[:4]) if fecha else None,
            })
        return out

    def _ir_primera_pagina(self):
        """SEACE recuerda la ultima pagina vista: se vuelve a la 1 antes de leer resultados."""
        p = self.page
        pg = f'[id="{FORM}:dtProcesos_paginator_bottom"]'
        first = p.locator(f"{pg} .ui-paginator-first")
        if first.count() == 0 or "ui-state-disabled" in (first.first.get_attribute("class") or ""):
            return
        antes = p.inner_text(pg)
        first.first.click()
        p.wait_for_function(
            """(a) => { const e = document.getElementById('tbBuscador:idFormBuscarProceso:dtProcesos_paginator_bottom');
                        return e && e.innerText !== a; }""",
            arg=antes, timeout=30000)
        time.sleep(1.0)

    def _siguiente_pagina(self) -> bool:
        p = self.page
        pg = f'[id="{FORM}:dtProcesos_paginator_bottom"]'
        nxt = p.locator(f"{pg} .ui-paginator-next")
        if nxt.count() == 0 or "ui-state-disabled" in (nxt.first.get_attribute("class") or ""):
            return False
        antes = p.inner_text(pg)
        nxt.first.click()
        p.wait_for_function(
            """(a) => { const e = document.getElementById('tbBuscador:idFormBuscarProceso:dtProcesos_paginator_bottom');
                        return e && e.innerText !== a; }""",
            arg=antes,
            timeout=30000,
        )
        pausa()
        return True

    # ---- ficha ---------------------------------------------------------
    def leer_ficha(self, ri: str) -> dict | None:
        """Abre la ficha de la fila `ri` en una pestana nueva y devuelve sus datos."""
        p = self.page
        p.evaluate(f"document.getElementById('{FORM}').target = '_blank'")
        try:
            with self.ctx.expect_page(timeout=30000) as info:
                p.locator(f'tr[data-ri="{ri}"] img[id$="grafichaSel"]').first.click()
            f = info.value
        finally:
            p.evaluate(f"document.getElementById('{FORM}').target = ''")
        try:
            f.wait_for_load_state("networkidle", timeout=45000)
            f.wait_for_selector('[id="tbFicha:dtCronograma"]', timeout=30000)
            try:
                f.wait_for_selector('[id="tbFicha:dtEntidadContrata"] tbody td', timeout=8000)
            except PWTimeout:
                pass
            data = f.evaluate(JS_FICHA)
            guard = 0
            while data["hasNext"] and guard < 10:   # documentos paginados
                guard += 1
                pg = f.locator('[id="tbFicha:dtDocumentos_paginator_bottom"] .ui-paginator-next').first
                pg.click()
                time.sleep(1.5)
                more = f.evaluate(JS_FICHA)
                known = {(d["uuid"], d["filename"]) for d in data["docs"]}
                data["docs"] += [d for d in more["docs"] if (d["uuid"], d["filename"]) not in known]
                data["hasNext"] = more["hasNext"]
            return data
        except Exception as e:  # noqa: BLE001
            self.log(f"   ! ficha fallo: {e}")
            return None
        finally:
            f.close()

    # ---- flujo completo ------------------------------------------------
    def guardar_ficha(self, c, nid: str, ficha: dict):
        crono = ficha["cronograma"]
        cierre = None
        for etapa, ini, fin in (r[:3] for r in crono):
            if re.search(r"present", etapa, re.I) and re.search(r"propuest|ofert", etapa, re.I):
                cierre = db.parse_fecha(fin)
                break
        ruc = ficha["entidad"][0] if ficha["entidad"] else None
        c.execute("DELETE FROM cronograma WHERE nid_proceso=?", (nid,))
        c.execute("DELETE FROM documentos WHERE nid_proceso=?", (nid,))
        for etapa, ini, fin in (r[:3] for r in crono):
            c.execute("INSERT INTO cronograma VALUES (?,?,?,?)",
                      (nid, etapa, db.parse_fecha(ini), db.parse_fecha(fin)))
        for d in ficha["docs"]:
            c.execute(
                "INSERT INTO documentos (nid_proceso, etapa, documento, archivo_uuid, filename, tamano, fecha)"
                " VALUES (?,?,?,?,?,?,?)",
                (nid, d["etapa"], d["documento"], d["uuid"], d["filename"], d["tamano"],
                 db.parse_fecha(d["fecha"])),
            )
        c.execute(
            "UPDATE licitaciones SET ficha_ok=1, ficha_json=?, cierre_propuestas=?, ruc=? WHERE nid_proceso=?",
            (json.dumps(ficha["info"], ensure_ascii=False), cierre, ruc, nid),
        )

    def scrapear(self, palabra: str, anio: int, refrescar: bool = False) -> dict:
        t0 = db.now()
        with db.conn() as c:
            cur = c.execute("INSERT INTO corridas (inicio, palabra, anio, estado) VALUES (?,?,?,'corriendo')",
                            (t0, palabra, anio))
            run_id = cur.lastrowid
        total = nuevas = 0
        try:
            total_res = self.buscar(palabra, anio)
            self.log(f"[{palabra} / {anio}] {total_res} resultados")
            while True:
                filas = self._filas_pagina()
                for f in filas:
                    with db.conn() as c:
                        es_nueva = db.upsert_licitacion(c, f, palabra)
                        ya = c.execute("SELECT ficha_ok FROM licitaciones WHERE nid_proceso=?",
                                       (f["nid_proceso"],)).fetchone()["ficha_ok"]
                    total += 1
                    nuevas += int(es_nueva)
                    if es_nueva or not ya or refrescar:
                        self.log(f"  {'NUEVA ' if es_nueva else '      '}{f['nomenclatura']} - {f['entidad'][:40]}")
                        pausa()
                        ficha = self.leer_ficha(f["ri"])
                        if ficha:
                            with db.conn() as c:
                                self.guardar_ficha(c, f["nid_proceso"], ficha)
                if not self._siguiente_pagina():
                    break
            estado, err = "ok", None
        except Exception as e:  # noqa: BLE001
            estado, err = "error", str(e)
            self.log(f"  ERROR: {e}")
        with db.conn() as c:
            c.execute("UPDATE corridas SET fin=?, encontradas=?, nuevas=?, estado=?, error=? WHERE id=?",
                      (db.now(), total, nuevas, estado, err, run_id))
        return {"palabra": palabra, "anio": anio, "encontradas": total, "nuevas": nuevas,
                "estado": estado, "error": err}

    # ---- descarga de documentos ---------------------------------------
    def descargar_docs(self, nid_proceso: str) -> list[str]:
        """Descarga los PDF de una licitacion (hay que reabrir su ficha en una sesion nueva)."""
        with db.conn() as c:
            lic = c.execute("SELECT * FROM licitaciones WHERE nid_proceso=?", (nid_proceso,)).fetchone()
            docs = c.execute("SELECT rowid, * FROM documentos WHERE nid_proceso=?", (nid_proceso,)).fetchall()
        if not lic or not docs:
            return []
        palabra = (lic["palabras"] or "fotocopiadora").split(",")[0]
        self.buscar(palabra, lic["anio"])
        ri = None
        while True:
            for f in self._filas_pagina():
                if f["nid_proceso"] == nid_proceso:
                    ri = f["ri"]
                    break
            if ri is not None or not self._siguiente_pagina():
                break
        if ri is None:
            raise RuntimeError("No se encontro la licitacion en la busqueda actual")
        p = self.page
        p.evaluate(f"document.getElementById('{FORM}').target = '_blank'")
        try:
            with self.ctx.expect_page(timeout=30000) as info:
                p.locator(f'tr[data-ri="{ri}"] img[id$="grafichaSel"]').first.click()
            f = info.value
        finally:
            p.evaluate(f"document.getElementById('{FORM}').target = ''")
        f.wait_for_selector('[id="tbFicha:dtDocumentos"]')
        dest = config.DOCS_DIR / re.sub(r"[^\w.-]", "_", f"{lic['nomenclatura']}_{nid_proceso}")
        dest.mkdir(parents=True, exist_ok=True)
        saved = []
        for d in docs:
            if not d["archivo_uuid"]:
                continue
            link = f.locator(f'a[onclick*="{d["archivo_uuid"]}"]').first
            try:
                with f.expect_download(timeout=120000) as dl:
                    link.click()
                name = re.sub(r"[^\w.\- ]", "_", d["filename"] or dl.value.suggested_filename)
                path = dest / name
                if self.headless:
                    # En headless save_as/ctx.request cierran el contexto: se baja la URL con las cookies.
                    url = dl.value.url
                    cookies = "; ".join(f"{c['name']}={c['value']}" for c in self.ctx.cookies([url]))
                    ua = f.evaluate("navigator.userAgent")
                    req = urllib.request.Request(url, headers={"Cookie": cookies, "User-Agent": ua})
                    with urllib.request.urlopen(req, timeout=180) as r:
                        path.write_bytes(r.read())
                else:
                    dl.value.save_as(path)
                saved.append(str(path))
                with db.conn() as c:
                    c.execute("UPDATE documentos SET local_path=? WHERE rowid=?", (str(path), d["rowid"]))
                pausa()
            except Exception as e:  # noqa: BLE001
                self.log(f"   ! descarga fallo {d['filename']}: {e}")
        f.close()
        return saved

    def _debug(self, name: str):
        config.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        try:
            self.page.screenshot(path=str(config.DEBUG_DIR / f"{name}.png"), full_page=True)
        except Exception:  # noqa: BLE001
            pass


def correr(keywords=None, anios=None, headless=False, refrescar=False, log=print) -> list[dict]:
    db.init()
    keywords = keywords or config.KEYWORDS
    anios = anios or sorted(set(config.ANIOS) | {date.today().year})
    res = []
    with Scraper(headless=headless, log=log) as s:
        for a in anios:
            for k in keywords:
                res.append(s.scrapear(k, a, refrescar=refrescar))
                pausa(2, 4)
    return res


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--refrescar", action="store_true", help="vuelve a leer las fichas ya guardadas")
    ap.add_argument("-k", "--keyword", action="append")
    ap.add_argument("-a", "--anio", action="append", type=int)
    a = ap.parse_args()
    for r in correr(a.keyword, a.anio, a.headless, a.refrescar):
        print(r)
