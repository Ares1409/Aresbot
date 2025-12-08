import os
import json
import datetime
import requests
from flask import Flask, request
from openai import OpenAI

# -------------------------
# Configuración básica
# -------------------------

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_FINANZAS = os.getenv("NOTION_DB_FINANZAS")

# El cliente de OpenAI usa OPENAI_API_KEY del entorno
client = OpenAI()

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# -------------------------
# Utilidades generales
# -------------------------

def send_message(chat_id: int, text: str):
    """Envía un mensaje de texto a Telegram."""
    try:
        requests.post(TELEGRAM_URL, json={
            "chat_id": chat_id,
            "text": text
        }, timeout=10)
    except Exception as e:
        print(f"[ERROR] Enviando mensaje a Telegram: {e}")

def get_current_month_range():
    """Devuelve (inicio_iso, fin_iso_exclusivo) del mes actual."""
    today = datetime.date.today()
    first_day = today.replace(day=1)
    # mes siguiente
    if first_day.month == 12:
        next_month = first_day.replace(year=first_day.year + 1, month=1, day=1)
    else:
        next_month = first_day.replace(month=first_day.month + 1, day=1)
    return first_day.isoformat(), next_month.isoformat()

# -------------------------
# Notion: escritura
# -------------------------

def create_financial_record(movimiento: str, tipo: str, monto: float,
                            categoria: str, fecha_iso: str):
    """Crea una nueva fila en la base de datos de Notion."""
    data = {
        "parent": {"database_id": NOTION_DB_FINANZAS},
        "properties": {
            "Movimiento": {"title": [{"text": {"content": movimiento}}]},
            "Tipo": {"select": {"name": tipo}},
            "Monto": {"number": float(monto)},
            "Categoría": {"select": {"name": categoria}},
            "Área": {"select": {"name": "Finanzas personales"}},
            "Fecha": {"date": {"start": fecha_iso}}
        }
    }

    try:
        resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            json=data,
            timeout=15
        )
        if resp.status_code >= 300:
            print(f"[ERROR] Notion create page: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[ERROR] Llamando a Notion: {e}")

# -------------------------
# Notion: lectura / resumen
# -------------------------

def query_notion_sum(tipo: str | None,
                     start_date_iso: str,
                     end_date_iso: str) -> float:
    """
    Suma el campo 'Monto' filtrando por rango de fechas y tipo (Ingreso/Egreso).
    Si tipo es None, no filtra por tipo.
    """
    total = 0.0
    has_more = True
    next_cursor = None

    while has_more:
        filtro_and = [
            {
                "property": "Fecha",
                "date": {"on_or_after": start_date_iso}
            },
            {
                "property": "Fecha",
                "date": {"before": end_date_iso}
            }
        ]

        if tipo:
            filtro_and.append({
                "property": "Tipo",
                "select": {"equals": tipo}
            })

        payload: dict = {
            "filter": {"and": filtro_and}
        }

        if next_cursor:
            payload["start_cursor"] = next_cursor

        try:
            resp = requests.post(
                f"https://api.notion.com/v1/databases/{NOTION_DB_FINANZAS}/query",
                headers=NOTION_HEADERS,
                json=payload,
                timeout=20
            )
            if resp.status_code >= 300:
                print(f"[ERROR] Notion query: {resp.status_code} {resp.text}")
                break

            data = resp.json()
            for page in data.get("results", []):
                props = page.get("properties", {})
                monto = props.get("Monto", {}).get("number")
                if isinstance(monto, (int, float)):
                    total += float(monto)

            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
        except Exception as e:
            print(f"[ERROR] Consultando Notion (sum): {e}")
            break

    return total


def get_month_summary():
    """
    Devuelve un dict con ingresos, gastos y balance del mes actual
    y un texto resumen para mostrar.
    """
    ini, fin = get_current_month_range()
    ingresos = query_notion_sum("Ingreso", ini, fin)
    gastos = query_notion_sum("Egreso", ini, fin)
    balance = ingresos - gastos

    texto = (
        f"Resumen del mes actual:\n"
        f"- Ingresos: {ingresos:.2f}\n"
        f"- Gastos:  {gastos:.2f}\n"
        f"- Balance: {balance:.2f}"
    )

    return {
        "ingresos": ingresos,
        "gastos": gastos,
        "balance": balance,
        "texto": texto
    }

# -------------------------
# IA con GPT-5-mini
# -------------------------

def ask_finance_ai(user_text: str) -> str:
    """
    Usa gpt-5-mini para dar una respuesta más inteligente
    usando como contexto el resumen del mes actual.
    """
    resumen = get_month_summary()
    contexto = (
        "Eres Ares1409, un asistente financiero personal. "
        "Respondes en español, de forma clara, profesional y directa.\n\n"
        f"Datos disponibles de este mes:\n"
        f"- Ingresos totales: {resumen['ingresos']:.2f}\n"
        f"- Gastos totales: {resumen['gastos']:.2f}\n"
        f"- Balance: {resumen['balance']:.2f}\n\n"
        f"Pregunta del usuario:\n{user_text}\n\n"
        "Da una explicación corta y como máximo 3 recomendaciones concretas."
    )

    try:
        response = client.responses.create(
            model="gpt-5-mini",
            input=contexto,
        )

        # Extrae el texto de la primera salida
        try:
            contents = response.output[0].content
            parts = []
            for c in contents:
                # Los objetos de tipo texto suelen traer .text
                if hasattr(c, "text"):
                    parts.append(c.text)
            text = "\n".join(parts).strip()
            if text:
                return text
        except Exception as inner:
            print(f"[WARN] Leyendo salida de OpenAI: {inner}")

        return "La IA no pudo generar una respuesta útil en este momento."
    except Exception as e:
        print(f"[ERROR] Llamando a OpenAI: {e}")
        return (
            "No pude consultar la IA en este momento.\n\n"
            f"Detalle técnico: {e}"
        )

# -------------------------
# Lógica de comandos
# -------------------------

def handle_gasto(text_original: str, chat_id: int):
    contenido = text_original.split(":", 1)[1].strip()
    partes = contenido.split(" ", 1)

    try:
        monto_str = partes[0].replace(",", "")
        monto = float(monto_str)
    except Exception:
        send_message(chat_id, "Formato no válido. Ejemplo: gasto: 150 tacos")
        return

    descripcion = partes[1] if len(partes) > 1 else "Sin descripción"
    hoy_iso = datetime.date.today().isoformat()

    create_financial_record(
        movimiento=descripcion,
        tipo="Egreso",
        monto=monto,
        categoria="General",
        fecha_iso=hoy_iso
    )

    send_message(chat_id, f"✔ Gasto registrado: {monto} – {descripcion}")


def handle_ingreso(text_original: str, chat_id: int):
    contenido = text_original.split(":", 1)[1].strip()
    partes = contenido.split(" ", 1)

    try:
        monto_str = partes[0].replace(",", "")
        monto = float(monto_str)
    except Exception:
        send_message(chat_id, "Formato no válido. Ejemplo: ingreso: 9000 sueldo")
        return

    descripcion = partes[1] if len(partes) > 1 else "Sin descripción"
    hoy_iso = datetime.date.today().isoformat()

    create_financial_record(
        movimiento=descripcion,
        tipo="Ingreso",
        monto=monto,
        categoria="General",
        fecha_iso=hoy_iso
    )

    send_message(chat_id, f"✔ Ingreso registrado: {monto} – {descripcion}")


def handle_simple_queries(text_lower: str, chat_id: int) -> bool:
    """
    Maneja consultas sencillas como:
    - gastos este mes
    - ingresos este mes
    - balance del mes
    Devuelve True si atendió la consulta, False si no.
    """
    t = text_lower

    # Total de gastos del mes
    if "gasto" in t and "mes" in t:
        ini, fin = get_current_month_range()
        gastos = query_notion_sum("Egreso", ini, fin)
        send_message(chat_id, f"Este mes llevas gastado: {gastos:.2f}")
        return True

    # Total de ingresos del mes
    if "ingreso" in t and "mes" in t:
        ini, fin = get_current_month_range()
        ingresos = query_notion_sum("Ingreso", ini, fin)
        send_message(chat_id, f"Este mes llevas ingresado: {ingresos:.2f}")
        return True

    # Balance del mes
    if "balance" in t or ("resumen" in t and "mes" in t):
        resumen = get_month_summary()
        send_message(chat_id, resumen["texto"])
        return True

    return False


def handle_saludo(text_lower: str, chat_id: int) -> bool:
    saludos = [
        "hola", "buenas", "buenos dias", "buenos días",
        "buenas tardes", "buenas noches", "hey", "qué onda", "que onda"
    ]
    if any(s in text_lower for s in saludos):
        send_message(
            chat_id,
            "Hola, ¿en qué puedo ayudarte hoy?\n\n"
            "Ejemplos:\n"
            "- gasto: 150 tacos\n"
            "- ingreso: 9000 sueldo\n"
            "- gastos este mes\n"
            "- ingresos este mes\n"
            "- balance del mes\n"
            "- estado finanzas"
        )
        return True
    return False

# -------------------------
# Flask routes (webhook)
# -------------------------

@app.route("/", methods=["GET"])
def home():
    return "Ares1409 bot OK", 200


@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()
    print(f"[DEBUG] Update recibido: {json.dumps(data, ensure_ascii=False)}")

    if not data or "message" not in data:
        return "OK", 200

    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")

    if not text:
        return "OK", 200

    text_original = text.strip()
    text_lower = text_original.lower()

    # 1) Comandos de registro
    if text_lower.startswith("gasto:"):
        handle_gasto(text_original, chat_id)
        return "OK", 200

    if text_lower.startswith("ingreso:"):
        handle_ingreso(text_original, chat_id)
        return "OK", 200

    # 2) Saludos simples
    if handle_saludo(text_lower, chat_id):
        return "OK", 200

    # 3) Consultas financieras simples
    if handle_simple_queries(text_lower, chat_id):
        return "OK", 200

    # 4) Consultas con IA: estado de finanzas u otras preguntas abiertas
    if ("estado finanzas" in text_lower or
        "estado de finanzas" in text_lower or
        "como voy" in text_lower or
        "cómo voy" in text_lower or
        "como van mis finanzas" in text_lower or
        "cómo van mis finanzas" in text_lower):
        respuesta_ia = ask_finance_ai(text_original)
        send_message(chat_id, respuesta_ia)
        return "OK", 200

    # 5) Fallback: no entendido
    send_message(
        chat_id,
        "No reconocí ese comando.\n\n"
        "Puedes probar con:\n"
        "- gasto: 150 tacos\n"
        "- ingreso: 9000 sueldo\n"
        "- gastos este mes\n"
        "- ingresos este mes\n"
        "- balance del mes\n"
        "- estado finanzas"
    )
    return "OK", 200


if __name__ == "__main__":
    # Para pruebas locales (en Render se usará gunicorn)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
