# Licitaciones SEACE · fotocopiadoras

Web personal que busca en el buscador público de SEACE (OECE) licitaciones de venta/alquiler de
fotocopiadoras, las guarda en SQLite y las muestra en una página con filtros, seguimiento y alertas.

## Uso
1. `iniciar.bat` (o `.venv\Scripts\python -m uvicorn app.main:app`) y abrir http://localhost:8000
2. Botón **Buscar nuevas ahora** para lanzar el scraper (se abre una ventana de Chrome; no la cierres).
   También corre solo cada `SCRAPE_CADA_HORAS` (app/config.py) mientras el servidor esté encendido.
3. Clic en una licitación → cronograma, documentos, estado (interesante/postulada/descartada) y notas.
   "Descargar bases" baja los PDF a `data/documentos/`.

Solo scraper por consola: `buscar_ahora.bat -k fotocopiadora -a 2026` (`--refrescar` relee las fichas).

## Cómo funciona
SEACE usa JSF/PrimeFaces + **reCAPTCHA v3 invisible**: el token lo genera el JS de la página, así que se
maneja Chrome real con Playwright (perfil persistente en `data/browser_profile`). No se evade ningún
captcha: si el puntaje es bajo SEACE devuelve 0 resultados y el scraper lo registra como error.
Cada licitación se identifica por `nid_proceso` (la nomenclatura puede repetirse).

## Configuración (`app/config.py`)
`KEYWORDS`, `ANIOS`, `RELEVANTE_RE` (qué se considera relevante), `SCRAPE_CADA_HORAS`, `BROWSER_CHANNEL`.

## Alertas (opcional, variables de entorno)
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Email: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `MAIL_TO`
- `SEACE_HEADLESS=1` ejecuta sin ventana (puede bajar el puntaje reCAPTCHA; probar antes).

## Mantenimiento
Si SEACE cambia su HTML, los selectores están en `app/scraper.py` (`JS_PARSE_ROWS`, `JS_FICHA`).
Capturas de errores en `data/debug/`.
