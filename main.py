import os
import json
import requests
import datetime
from flask import Flask, request

app = Flask(__name__)

# =======================
#  CONFIGURACIÓN GLOBAL
# =======================

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

# Notion
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_FINANZAS = os.getenv("NOTION_DB_FINANZAS")
NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_HEADERS = {
    "Authorization": f"Bearer {OPENAI_API_KEY}",
    "Content-Type": "application/json",
}


# =======================
#  FUNCIONES AUXILIARES
# =======================

def send_message(chat_id, text):
    """Envia un mensaje de texto a Telegram."""
    try:
        requests.post(
            TELEGRAM_URL,
            json={
                "chat_id": chat_id,
                "text": text,
            },
            timeout=10,
        )
    except Exception as e:
        print("[ERROR] send_message:", e)


def create_financial_record(movimiento, tipo, monto, categoria, fecha_iso):
    """
    Crea un registro financiero en Notion.

    movimiento: descripción (texto)
    tipo: "Ingreso" o "Egreso"
    monto: string/float
    categoria: string (ej. "General")
    fecha_iso: "YYYY-MM-DD"
    """
    if not NOTION_TOKEN or not NOTION_DB_FINANZAS:
        print("[ERROR] Falta NOTION_TOKEN o NOTION_DB_FINANZAS.")
        return

    page_url = f"{NOTION_BASE_URL}/pages"

    data = {
        "parent": {"database_id": NOTION_DB_FINANZAS},
        "properties": {
            "Movimiento": {
                "title": [{"text": {"content": movimiento}}],
            },
            "Tipo": {
                "select": {"name": tipo},
            },
            "Monto": {
                "number": float(monto),
            },
            "Categoría": {
                "select": {"name": categoria},
            },
            "Área": {
                "select": {"name": "Finanzas personales"},
            },
            "Fecha": {
                "date": {"start": fecha_iso},
            },
        },
    }

    try:
        resp = requests.post(page_url, headers=NOTION_HEADERS, json=data, timeout=15)
        if resp.status_code >= 300:
            print("[ERROR] create_financial_record:", resp.status_code, resp.text)
    except Exception as e:
        print("[ERROR] create_financial_record EXCEPTION:", e)


def get_financial_summary_context(days: int = 30) -> str:
    """
    Lee los últimos 'days' días de la base de Notion y arma
    un contexto de texto para pasárselo a la IA.
    """
    if not NOTION_TOKEN or not NOTION_DB_FINANZAS:
        return "No hay conexión configurada con Notion."

    query_url = f"{NOTION_BASE_URL}/databases/{NOTION_DB_FINANZAS}/query"

    try:
        resp = requests.post(query_url, headers=NOTION_HEADERS, json={}, timeout=20)
        data = resp.json()

        if resp.status_code >= 300:
            print("[ERROR] Query Notion:", resp.status_code, resp.text)
            return "No pude leer datos de Notion."

        rows = data.get("results", [])
        hoy = datetime.date.today()

        movimientos = []

        for row in rows:
            props = row["properties"]

            # Fecha (ISO)
            fecha_val = props["Fecha"]["date"]["start"] if props["Fecha"]["date"] else None
            if not fecha_val:
                continue

            fecha = datetime.date.fromisoformat(fecha_val)

            # Filtrar últimos N días
            if (hoy - fecha).days > days:
                continue

            # Movimiento
            mov_title = props["Movimiento"]["title"]
            movimiento = mov_title[0]["plain_text"] if mov_title else ""

            # Tipo
            tipo = props["Tipo"]["select"]["name"] if props["Tipo"]["select"] else ""

            # Monto
            monto = props["Monto"]["number"] or 0

            # Categoría
            categoria = (
                props["Categoría"]["select"]["name"]
                if props["Categoría"]["select"]
                else "Sin categoría"
            )

            movimientos.append(
                f"{fecha.isoformat()} | {tipo} | {monto} | {categoria} | {movimiento}"
            )

        if not movimientos:
            return "No hay movimientos recientes en tu base."

        return "\n".join(movimientos)

    except Exception as e:
        print("[ERROR] get_financial_summary_context:", e)
        return "Error al leer datos de Notion."


def call_finance_ai(context: str) -> str:
    """
    Llama a OpenAI (gpt-5-mini) para generar un resumen financiero
    y recomendaciones basadas en el contexto (movimientos).
    """
    if not OPENAI_API_KEY:
        return "No tengo configurada la clave de OpenAI en el servidor."

    prompt = f"""
Eres un asesor financiero personal. A partir de los movimientos de la base de datos
del usuario (ingresos y gastos), genera un resumen y recomendaciones claras.

Movimientos (uno por línea con formato: fecha | tipo | monto | categoría | descripción):
{context}

En tu respuesta:

1. Da primero un resumen con totales de ingresos, gastos y saldo aproximado.
2. Menciona las categorías principales y en qué se está yendo el dinero.
3. Señala de 3 a 5 oportunidades de mejora concretas y accionables.
4. Responde en español, en un tono sencillo y directo.
"""

    body = {
        "model": "gpt-5-mini",
        "messages": [
            {
                "role": "system",
                "content": "Eres un asesor financiero que habla en español y da respuestas claras y prácticas.",
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    }

    try:
        resp = requests.post(
            OPENAI_URL, headers=OPENAI_HEADERS, json=body, timeout=40
        )

        # Errores típicos: cuota / plan
        if resp.status_code == 429:
            return (
                "No pude consultar la IA en este momento por límite de uso de la API "
                "(código 429: insufficient_quota). Revisa tu plan y facturación de OpenAI."
            )

        if resp.status_code >= 300:
            print("[ERROR] OpenAI:", resp.status_code, resp.text)
            return "Hubo un error al consultar la IA para analizar tus finanzas."

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content.strip()

    except Exception as e:
        print("[ERROR] call_finance_ai:", e)
        return "Ocurrió un error al llamar a la IA para analizar tus finanzas."


# =======================
#  WEBHOOK TELEGRAM
# =======================

@app.route("/", methods=["POST"])
def webhook():
    """Endpoint que recibe las actualizaciones de Telegram."""
    data = request.get_json()
    print("[WEBHOOK]", json.dumps(data, ensure_ascii=False))

    if "message" not in data:
        return "OK"

    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()

    if not text:
        send_message(chat_id, "Solo puedo leer mensajes de texto por ahora.")
        return "OK"

    lower = text.lower()

    # ---------- Registrar GASTO ----------
    # Formato: "gasto: 150 tacos"
    if lower.startswith("gasto:"):
        contenido = text.split(":", 1)[1].strip()
        partes = contenido.split(" ", 1)

        monto = partes[0].replace(",", ".")
        descripcion = partes[1] if len(partes) > 1 else "Sin descripción"

        hoy = datetime.date.today().isoformat()

        create_financial_record(
            movimiento=descripcion,
            tipo="Egreso",
            monto=monto,
            categoria="General",
            fecha_iso=hoy,
        )

        send_message(chat_id, f"✔ Gasto registrado: {monto} - {descripcion}")
        return "OK"

    # ---------- Registrar INGRESO ----------
    # Formato: "ingreso: 9000 sueldo"
    if lower.startswith("ingreso:"):
        contenido = text.split(":", 1)[1].strip()
        partes = contenido.split(" ", 1)

        monto = partes[0].replace(",", ".")
        descripcion = partes[1] if len(partes) > 1 else "Sin descripción"

        hoy = datetime.date.today().isoformat()

        create_financial_record(
            movimiento=descripcion,
            tipo="Ingreso",
            monto=monto,
            categoria="General",
            fecha_iso=hoy,
        )

        send_message(chat_id, f"✔ Ingreso registrado: {monto} - {descripcion}")
        return "OK"

    # ---------- Estado de finanzas ----------
    # Ejemplo: "estado finanzas" o "estado de finanzas"
    if "estado" in lower and "finanza" in lower:
        contexto = get_financial_summary_context(days=30)
        respuesta = call_finance_ai(contexto)
        send_message(chat_id, respuesta)
        return "OK"

    # ---------- Mensaje por defecto ----------
    ayuda = (
        "No entendí el comando.\n\n"
        "Ejemplos que puedes usar:\n"
        "• gasto: 150 tacos\n"
        "• gasto: 850 renta\n"
        "• ingreso: 9000 sueldo\n"
        "• estado finanzas\n"
    )
    send_message(chat_id, ayuda)
    return "OK"


@app.route("/", methods=["GET"])
def home():
    return "Ares1409 bot funcionando."


if __name__ == "__main__":
    # En Render se usa PORT, localmente podemos usar 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
