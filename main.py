import os
import json
import requests
import datetime
from flask import Flask, request
from openai import OpenAI

app = Flask(__name__)

# =========================
#  CONFIGURACIÓN BÁSICA
# =========================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_FINANZAS = os.getenv("NOTION_DB_FINANZAS")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_PAGES_URL = f"{NOTION_BASE_URL}/pages"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# Cliente OpenAI (GPT-4o mini)
oa_client = OpenAI(api_key=OPENAI_API_KEY)


# =========================
#  FUNCIONES AUXILIARES
# =========================

def send_message(chat_id: int, text: str):
    """Envía un mensaje de texto a Telegram."""
    try:
        requests.post(
            TELEGRAM_URL,
            json={"chat_id": chat_id, "text": text}
        )
    except Exception as e:
        print(f"[ERROR] Enviando mensaje a Telegram: {e}")


def create_financial_record(movimiento: str,
                            tipo: str,
                            monto: float,
                            categoria: str,
                            fecha: str):
    """
    Crea un registro en la base de datos de FINANZAS Ares1409 en Notion.
    Columnas esperadas:
    - Movimiento (title)
    - Tipo (select)
    - Monto (number)
    - Categoría (select)
    - Área (select)
    - Fecha (date)
    """
    data = {
        "parent": {"database_id": NOTION_DB_FINANZAS},
        "properties": {
            "Movimiento": {
                "title": [
                    {"text": {"content": movimiento}}
                ]
            },
            "Tipo": {
                "select": {"name": tipo}
            },
            "Monto": {
                "number": float(monto)
            },
            "Categoría": {
                "select": {"name": categoria}
            },
            "Área": {
                "select": {"name": "Finanzas personales"}
            },
            "Fecha": {
                "date": {"start": fecha}
            }
        }
    }

    try:
        resp = requests.post(
            NOTION_PAGES_URL,
            headers=NOTION_HEADERS,
            json=data
        )
        if resp.status_code >= 300:
            print("[ERROR] Notion create:", resp.status_code, resp.text)
            return False
        return True
    except Exception as e:
        print(f"[ERROR] Creando registro en Notion: {e}")
        return False


def get_financial_summary_context(days: int = 30) -> str:
    """
    Consulta Notion y genera un contexto de los últimos 'days' días
    para que la IA pueda analizar las finanzas.
    """
    query_url = f"{NOTION_BASE_URL}/databases/{NOTION_DB_FINANZAS}/query"
    body = {
        "page_size": 100
    }

    try:
        resp = requests.post(query_url, headers=NOTION_HEADERS, json=body)
        if resp.status_code >= 300:
            print("[ERROR] Notion query:", resp.status_code, resp.text)
            return "No se pudo leer la base de datos de finanzas en Notion."

        data = resp.json()
        results = data.get("results", [])

        hoy = datetime.date.today()
        lineas = []

        for page in results:
            props = page.get("properties", {})

            # Fecha
            fecha_str = (
                props.get("Fecha", {})
                .get("date", {})
                .get("start")
            )
            if not fecha_str:
                continue

            try:
                fecha = datetime.date.fromisoformat(fecha_str[:10])
            except Exception:
                continue

            if (hoy - fecha).days > days:
                continue

            # Movimiento (title)
            movimiento = ""
            mov_title = props.get("Movimiento", {}).get("title", [])
            if mov_title:
                movimiento = mov_title[0].get("plain_text", "")

            # Tipo
            tipo = (
                props.get("Tipo", {})
                .get("select", {})
                .get("name", "")
            )

            # Monto
            monto = props.get("Monto", {}).get("number", 0) or 0

            # Categoría
            categoria = (
                props.get("Categoría", {})
                .get("select", {})
                .get("name", "")
            )

            lineas.append(
                f"{fecha.isoformat()} | {tipo} | {monto} | {categoria} | {movimiento}"
            )

        if not lineas:
            return "No hay movimientos registrados en el periodo seleccionado."

        return "\n".join(lineas[:80])

    except Exception as e:
        print(f"[ERROR] Leyendo finanzas de Notion: {e}")
        return "Ocurrió un error al leer la base de datos de Notion."


def ask_gpt(prompt: str, contexto: str = "") -> str:
    """Consulta GPT-4o mini con un prompt y un contexto adicional."""
    try:
        mensaje_usuario = f"{prompt}\n\nContexto de movimientos:\n{contexto}"

        completion = oa_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres Ares1409, un asistente personal financiero. "
                        "Eres claro, profesional, directo y útil."
                    )
                },
                {"role": "user", "content": mensaje_usuario}
            ],
            temperature=0.2,
            max_tokens=400,
        )
        return completion.choices[0].message.content
    except Exception as e:
        print(f"[ERROR] Llamando a OpenAI: {e}")
        return f"No pude consultar la IA en este momento. Detalle técnico: {e}"


# =========================
#  RUTAS FLASK (WEBHOOK)
# =========================

@app.route("/", methods=["POST"])
def webhook():
    """Webhook que recibe las actualizaciones de Telegram."""
    data = request.get_json(force=True, silent=True) or {}
    print("[DEBUG] Update:", json.dumps(data, ensure_ascii=False))

    if "message" not in data:
        return "OK"

    message = data["message"]
    chat_id = message["chat"]["id"]
    text_raw = message.get("text", "") or ""

    if not text_raw:
        send_message(chat_id, "Por ahora solo proceso texto.")
        return "OK"

    text = text_raw.strip()
    text_lower = text.lower()

    # -------- NORMALIZACIONES BÁSICAS --------
    # Quitamos dobles espacios y espacios alrededor de ':'
    text_no_spaces = " ".join(text_lower.split())
    text_compacto = text_no_spaces.replace(" : ", ":").replace(" :", ":").replace(": ", ":")

    # -------------------------
    # 1) REGISTRO DE GASTO
    # Acepta variantes:
    # "gasto:150 tacos", "gasto: 150 tacos", "GASTO : 150 tacos"
    # -------------------------
    if text_compacto.startswith("gasto:"):
        contenido = text_compacto[len("gasto:"):].strip()
        partes = contenido.split(" ", 1)

        if not partes:
            send_message(chat_id, "Formato: gasto: Monto descripción")
            return "OK"

        monto_str = partes[0]
        descripcion = partes[1] if len(partes) > 1 else "Gasto sin descripción"

        try:
            monto = float(monto_str)
        except ValueError:
            send_message(chat_id, "El monto debe ser un número. Ejemplo: gasto: 150 tacos")
            return "OK"

        hoy = datetime.date.today().isoformat()

        ok = create_financial_record(
            movimiento=descripcion,
            tipo="Egreso",
            monto=monto,
            categoria="General",
            fecha=hoy
        )

        if ok:
            send_message(chat_id, f"✔ Gasto registrado: {monto} - {descripcion}")
        else:
            send_message(chat_id, "Hubo un problema guardando el gasto en Notion.")
        return "OK"

    # -------------------------
    # 2) REGISTRO DE INGRESO
    # Acepta: "ingreso:9000 sueldo", "ingreso : 9000 sueldo", etc.
    # -------------------------
    if text_compacto.startswith("ingreso:"):
        contenido = text_compacto[len("ingreso:"):].strip()
        partes = contenido.split(" ", 1)

        if not partes:
            send_message(chat_id, "Formato: ingreso: Monto descripción")
            return "OK"

        monto_str = partes[0]
        descripcion = partes[1] if len(partes) > 1 else "Ingreso sin descripción"

        try:
            monto = float(monto_str)
        except ValueError:
            send_message(chat_id, "El monto debe ser un número. Ejemplo: ingreso: 9000 sueldo")
            return "OK"

        hoy = datetime.date.today().isoformat()

        ok = create_financial_record(
            movimiento=descripcion,
            tipo="Ingreso",
            monto=monto,
            categoria="General",
            fecha=hoy
        )

        if ok:
            send_message(chat_id, f"✔ Ingreso registrado: {monto} - {descripcion}")
        else:
            send_message(chat_id, "Hubo un problema guardando el ingreso en Notion.")
        return "OK"

    # -------------------------
    # 3) RESUMEN CON IA
    # Acepta cualquier texto que contenga "estado" y "finanzas"
    # Ej: "estado finanzas", "dame el estado de mis finanzas"
    # -------------------------
    if ("estado" in text_lower) and ("finanzas" in text_lower):
        contexto = get_financial_summary_context(days=30)
        respuesta = ask_gpt(
            "Analiza mis finanzas y dame un resumen y recomendaciones claras.",
            contexto=contexto
        )
        send_message(chat_id, respuesta)
        return "OK"

    # -------------------------
    # 4) AYUDA / START
    # -------------------------
    if text_lower in ("ayuda", "help", "/start"):
        ayuda = (
            "Soy Ares1409, tu asistente financiero.\n\n"
            "Comandos disponibles:\n"
            "- gasto: 150 tacos\n"
            "- ingreso: 9000 sueldo\n"
            "- estado finanzas\n"
        )
        send_message(chat_id, ayuda)
        return "OK"

    # -------------------------
    # 5) MENSAJES NO RECONOCIDOS
    # -------------------------
    send_message(
        chat_id,
        "No entendí el comando.\n\n"
        "Ejemplos:\n"
        "- gasto: 150 tacos\n"
        "- ingreso: 9000 sueldo\n"
        "- estado finanzas"
    )
    return "OK"


@app.route("/", methods=["GET"])
def home():
    return "Ares1409 bot funcionando."


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
