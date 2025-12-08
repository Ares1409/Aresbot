import os
import json
import requests
import datetime
from flask import Flask, request
from openai import OpenAI

# =====================================================
#  CONFIGURACIÓN GENERAL
# =====================================================

app = Flask(__name__)

# Tokens / claves
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Bases de datos reales
NOTION_DB_FINANZAS = os.getenv("NOTION_DB_FINANZAS")
NOTION_DB_TAREAS = os.getenv("NOTION_DB_TAREAS")
NOTION_DB_EVENTOS = os.getenv("NOTION_DB_EVENTOS")
NOTION_DB_PROYECTOS = os.getenv("NOTION_DB_PROYECTOS")

# URLs
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
NOTION_BASE_URL = "https://api.notion.com/v1"

# Cliente de OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# Encabezados Notion
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# =====================================================
#  FUNCIONES GENERALES
# =====================================================

def send_message(chat_id, text):
    """Enviar mensaje a Telegram."""
    try:
        requests.post(
            TELEGRAM_URL,
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
        )
    except Exception as e:
        print("Error enviando mensaje a Telegram:", e)


def hoy_iso():
    return datetime.date.today().isoformat()


def inicio_fin_mes():
    hoy = datetime.date.today()
    inicio = hoy.replace(day=1)
    if hoy.month == 12:
        fin = hoy.replace(year=hoy.year + 1, month=1, day=1)
    else:
        fin = hoy.replace(month=hoy.month + 1, day=1)
    return inicio.isoformat(), fin.isoformat()

# =====================================================
#  NOTION – CREAR REGISTROS
# =====================================================

def notion_create_page(db_id, props):
    """Crear página en Notion."""
    try:
        r = requests.post(
            f"{NOTION_BASE_URL}/pages",
            headers=NOTION_HEADERS,
            json={"parent": {"database_id": db_id}, "properties": props}
        )
        if r.status_code >= 300:
            print("ERROR creando en Notion:", r.text)
        return r
    except Exception as e:
        print("Error Notion:", e)


def create_finanza(desc, tipo, monto):
    props = {
        "Movimiento": {"title": [{"text": {"content": desc}}]},
        "Tipo": {"select": {"name": tipo}},
        "Monto": {"number": float(monto)},
        "Categoría": {"select": {"name": "General"}},
        "Área": {"select": {"name": "Finanzas personales"}},
        "Fecha": {"date": {"start": hoy_iso()}}
    }
    notion_create_page(NOTION_DB_FINANZAS, props)


def create_tarea(desc):
    props = {
        "Tarea": {"title": [{"text": {"content": desc}}]},
        "Estado": {"select": {"name": "Pendiente"}},
        "Área": {"select": {"name": "General"}},
        "Fecha": {"date": {"start": hoy_iso()}},
    }
    notion_create_page(NOTION_DB_TAREAS, props)


def create_evento(desc):
    props = {
        "Evento": {"title": [{"text": {"content": desc}}]},
        "Fecha": {"date": {"start": hoy_iso()}},
        "Área": {"select": {"name": "General"}},
        "Tipo de Evento": {"select": {"name": "General"}},
    }
    notion_create_page(NOTION_DB_EVENTOS, props)


def create_proyecto(nombre):
    props = {
        "Proyecto": {"title": [{"text": {"content": nombre}}]},
        "Área": {"select": {"name": "General"}},
        "Estado": {"select": {"name": "Activo"}},
        "Fecha Inicio": {"date": {"start": hoy_iso()}},
        "Impacto": {"select": {"name": "Medio"}},
    }
    notion_create_page(NOTION_DB_PROYECTOS, props)

# =====================================================
#  NOTION – CONSULTAS
# =====================================================

def resumen_finanzas():
    inicio, fin = inicio_fin_mes()

    query = {
        "filter": {
            "and": [
                {"property": "Fecha", "date": {"on_or_after": inicio}},
                {"property": "Fecha", "date": {"before": fin}}
            ]
        }
    }

    try:
        r = requests.post(
            f"{NOTION_BASE_URL}/databases/{NOTION_DB_FINANZAS}/query",
            headers=NOTION_HEADERS,
            json=query
        )
        data = r.json()
    except Exception as e:
        print("Error resumen finanzas:", e)
        return "Error consultando finanzas."

    ingresos = 0
    gastos = 0

    for row in data.get("results", []):
        props = row["properties"]
        tipo = props["Tipo"]["select"]["name"]
        monto = props["Monto"]["number"]

        if tipo == "Ingreso":
            ingresos += monto
        elif tipo == "Egreso":
            gastos += monto

    balance = ingresos - gastos

    return (
        f"*Resumen financiero del mes:*\n\n"
        f"• Ingresos: `{ingresos:,.2f}`\n"
        f"• Gastos: `{gastos:,.2f}`\n"
        f"• Balance: `{balance:,.2f}`"
    )

# =====================================================
#  OPENAI – GPT-4.1-mini
# =====================================================

def consultar_ia(texto_usuario: str) -> str:
    """Consulta la IA usando el modelo correcto GPT-4.1-mini."""

    prompt = (
        "Eres Ares1409, un asistente personal experto en finanzas, tareas, proyectos y eventos. "
        "Responde SIEMPRE en español, de forma clara y directa.\n\n"
        f"Usuario: {texto_usuario}\n\n"
        "Responde:"
    )

    try:
        respuesta = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            max_output_tokens=200
        )
        return respuesta.output[0].content[0].text
    except Exception as e:
        print("Error al consultar OpenAI:", e)
        return (
            "No pude consultar la IA en este momento. "
            "Revisa tu cuota de OpenAI o vuelve a intentarlo más tarde."
        )

# =====================================================
#  PARSEO COMANDOS
# =====================================================

AYUDA = (
    "*Ares1409 – Comandos:*\n\n"
    "• `gasto: 150 tacos`\n"
    "• `ingreso: 9000 sueldo`\n"
    "• `estado finanzas`\n"
    "• `tarea: enviar reporte`\n"
    "• `evento: junta mañana`\n"
    "• `proyecto: LoopMX`\n\n"
    "Si escribes algo libre, te respondo con IA."
)

# =====================================================
#  WEBHOOK
# =====================================================

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    msg = data.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    texto = (msg.get("text") or "").strip()
    lower = texto.lower()

    if not texto:
        return "OK"

    # ---- SALUDO (NO usa IA) ----
    if lower in ["hola", "hola!", "buenas", "buenos días", "buenos dias", "hey"]:
        send_message(chat_id, "Hola 👋 Soy Ares1409. ¿En qué te ayudo hoy?\n\nEscribe `ayuda` para ver mis comandos.")
        return "OK"

    if lower in ["ayuda", "/start", "/help"]:
        send_message(chat_id, AYUDA)
        return "OK"

    # ---- GASTO ----
    if lower.startswith("gasto:"):
        _, resto = texto.split(":", 1)
        partes = resto.strip().split(" ", 1)
        monto = float(partes[0])
        desc = partes[1] if len(partes) > 1 else "Sin descripción"
        create_finanza(desc, "Egreso", monto)
        send_message(chat_id, f"✔ Gasto registrado: {monto} – {desc}")
        return "OK"

    # ---- INGRESO ----
    if lower.startswith("ingreso:"):
        _, resto = texto.split(":", 1)
        partes = resto.strip().split(" ", 1)
        monto = float(partes[0])
        desc = partes[1] if len(partes) > 1 else "Sin descripción"
        create_finanza(desc, "Ingreso", monto)
        send_message(chat_id, f"✔ Ingreso registrado: {monto} – {desc}")
        return "OK"

    # ---- FINANZAS ----
    if "estado finanzas" in lower or "gastos este mes" in lower:
        send_message(chat_id, resumen_finanzas())
        return "OK"

    # ---- TAREAS ----
    if lower.startswith("tarea:"):
        desc = texto.split(":", 1)[1].strip()
        create_tarea(desc)
        send_message(chat_id, f"✔ Tarea creada: {desc}")
        return "OK"

    # ---- EVENTOS ----
    if lower.startswith("evento:"):
        desc = texto.split(":", 1)[1].strip()
        create_evento(desc)
        send_message(chat_id, f"✔ Evento creado: {desc}")
        return "OK"

    # ---- PROYECTOS ----
    if lower.startswith("proyecto:"):
        nombre = texto.split(":", 1)[1].strip()
        create_proyecto(nombre)
        send_message(chat_id, f"✔ Proyecto creado: {nombre}")
        return "OK"

    # ---- IA PARA TODO LO DEMÁS ----
    respuesta = consultar_ia(texto)
    send_message(chat_id, respuesta)
    return "OK"


@app.route("/", methods=["GET"])
def home():
    return "Ares1409 OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))

