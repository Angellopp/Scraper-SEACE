from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "licitaciones.db"
PROFILE_DIR = DATA_DIR / "browser_profile"   # perfil persistente de Chromium (ayuda al puntaje de reCAPTCHA v3)
DOCS_DIR = DATA_DIR / "documentos"
DEBUG_DIR = DATA_DIR / "debug"

BUSCADOR_URL = "https://prod2.seace.gob.pe/seacebus-uiwd-pub/buscadorPublico/buscadorPublico.xhtml"

# Navegador instalado a usar ("chrome", "msedge" o None para el Chromium de Playwright)
BROWSER_CHANNEL = "chrome"

# Palabras clave que se buscan en "Descripción del Objeto"
KEYWORDS = ["fotocopiadora", "copiadora", "multifuncional", "fotocopiado"]

# Años de convocatoria a revisar (el actual siempre se agrega)
ANIOS = [2026]

# Una licitacion se marca "relevante" si su descripcion coincide con esto
RELEVANTE_RE = r"(fotocopiad|copiador|equipos? de copiado|copiado)"
# "multifuncional" es ambiguo (losas, maquinaria...): solo cuenta si va con estas palabras y sin las de abajo
MULTIF_RE = r"(impresora|esc[aá]ner|scanner|equipos? multifuncional|alquiler|arrendamiento)"
NO_MULTIF_RE = r"(electroterap|losa|obra|tina|ahoyadora|perforadora|deportiv|construcci|creaci[oó]n|mejoramiento|infraestructura|cancha|saln|sal[oó]n|local multifuncional|agr[ií]cola|maquinaria)"
# ...salvo que sea compra de insumos/repuestos/mantenimiento (no es venta ni alquiler de equipos)
EXCLUIR_RE = r"(suministros?|t[oó]ner|toners|cartucho|tinta|repuesto|consumible|insumo|mantenimiento|papel )"

# Pausas entre acciones (segundos) para no cargar el servidor y parecer humano
PAUSA_MIN = 1.2
PAUSA_MAX = 2.8

# Intervalo del scraper automatico (horas)
SCRAPE_CADA_HORAS = 6
