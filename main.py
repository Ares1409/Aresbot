import os
import json
import requests
import datetime
from flask import Flask, request
from openai import OpenAI

# =========================
#  CONFIGURACIÓN
# =========================

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

NOTION_DB_FINANZAS = os.getenv("NOTION_DB_FINANZAS")
NOTION_DB_TAREAS = os.getenv("NOTION_DB_TAREAS")
NOTION_DB_EVENTOS = os.getenv("NOTION_DB_EVENTOS")
NOTION_DB_PROYECTOS = os.getenv("NOTION_DB_PROYECTOS")
NOTION_DB_HABITOS = os.getenv("NOTION_DB_HABITOS")

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

client = OpenAI(api_key=OPENAI_API_KEY)

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}

# =========================
#  UTILIDADES BÁSICAS
# =========================

def send_message(chat_id, text, reply_to=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    try:
        requests.post(TELEGRAM_URL, json=payload, timeout=15)
    except Exception as e:
        print("Error enviando mensaje a Telegram:", e)


def notion_create_page(database_id, properties):
    if not database_id:
        print("ERROR: database_id vacío al crear página en Notion.")
        return None
    data = {"parent": {"database_id": database_id}, "properties": properties}
    try:
        r = requests.post(
            f"{NOTION_BASE_URL}/pages",
            headers=NOTION_HEADERS,
            json=data,
            timeout=20,
        )
        if r.status_code >= 300:
            print("Error creando página en Notion:", r.status_code, r.text)
        return r
    except Exception as e:
        print("Error de red creando página en Notion:", e)
        return None


def notion_query(database_id, body):
    if not database_id:
        print("ERROR: database_id vacío al consultar Notion.")
        return {}
    try:
        r = requests.post(
            f"{NOTION_BASE_URL}/databases/{database_id}/query",
            headers=NOTION_HEADERS,
            json=body,
            timeout=25,
        )
        if r.status_code >= 300:
            print("Error consultando Notion:", r.status_code, r.text)
            return {}
        return r.json()
    except Exception as e:
        print("Error de red consultando Notion:", e)
        return {}


def hoy_iso():
    return datetime.date.today().isoformat()


def inicio_fin_mes_actual():
    hoy = datetime.date.today()
    inicio = hoy.replace(day=1)
    if hoy.month == 12:
        fin = hoy.replace(year=hoy.year + 1, month=1, day=1) - datetime.timedelta(days=1)
    else:
        fin = hoy.replace(month=hoy.month + 1, day=1) - datetime.timedelta(days=1)
    return inicio.isoformat(), fin.isoformat()


# =========================
#  CREACIÓN DE REGISTROS
# =========================

def create_financial_record(movimiento, tipo, monto, categoria="General",
                            area="Finanzas personales", fecha=None):
    if fecha is None:
        fecha = hoy_iso()
    properties = {
        "Movimiento": {"title": [{"text": {"content": movimiento}}]},
        "Tipo": {"select": {"name": tipo}},
        "Monto": {"number": float(monto)},
        "Categoría": {"select": {"name": categoria}},
        "Área": {"select": {"name": area}},
        "Fecha": {"date": {"start": fecha}},
    }
    notion_create_page(NOTION_DB_FINANZAS, properties)


def create_task(nombre, fecha=None, area="General", estado="Pendiente",
                prioridad="Media", contexto="General", notas=""):
    if fecha is None:
        fecha = hoy_iso()
    properties = {
        "Tarea": {"title": [{"text": {"content": nombre}}]},
        "Estado": {"select": {"name": estado}},
        "Área": {"select": {"name": area}},
        "Fecha": {"date": {"start": fecha}},
        "Prioridad": {"select": {"name": prioridad}},
        "Contexto": {"select": {"name": contexto}},
    }
    if notas:
        properties["Notas"] = {"rich_text": [{"text": {"content": notas[:1800]}}]}
    notion_create_page(NOTION_DB_TAREAS, properties)


def create_event(nombre, fecha, area="General", tipo_evento="General",
                 lugar="", notas=""):
    properties = {
        "Evento": {"title": [{"text": {"content": nombre}}]},
        "Fecha": {"date": {"start": fecha}},
        "Área": {"select": {"name": area}},
        "Tipo de Evento": {"select": {"name": tipo_evento}},
    }
    if lugar:
        properties["Lugar"] = {"rich_text": [{"text": {"content": lugar[:500]}}]}
    if notas:
        properties["Notas"] = {"rich_text": [{"text": {"content": notas[:1800]}}]}
    notion_create_page(NOTION_DB_EVENTOS, properties)


def create_project(nombre, area="General", estado="Activo",
                   fecha_inicio=None, fecha_fin=None,
                   impacto="Medio", notas=""):
    if fecha_inicio is None:
        fecha_inicio = hoy_iso()
    properties = {
        "Proyecto": {"title": [{"text": {"content": nombre}}]},
        "Área": {"select": {"name": area}},
        "Estado": {"select": {"name": estado}},
        "Fecha Inicio": {"date": {"start": fecha_inicio}},
        "Impacto": {"select": {"name": impacto}},
    }
    if fecha_fin:
        properties["Fecha objetivo fin"] = {"date": {"start": fecha_fin}}
    if notas:
        properties["Notas"] = {"rich_text": [{"text": {"content": notas[:1800]}}]}
    notion_create_page(NOTION_DB_PROYECTOS, properties)


def create_habit(nombre, area="General", estado="Activo",
                 numero=1, notas=""):
    properties = {
        "Hábito": {"title": [{"text": {"content": nombre}}]},
        "Área": {"select": {"name": area}},
        "Estado": {"select": {"name": estado}},
        "Número": {"number": int(numero)},
    }
    if notas:
        properties["Notas"] = {"rich_text": [{"text": {"content": notas[:1800]}}]}
    notion_create_page(NOTION_DB_HABITOS, properties)


# =========================
#  CONSULTAS E INFORMES
# =========================

def resumen_finanzas_mes():
    inicio, fin = inicio_fin_mes_actual()
    body = {
        "filter": {
            "and": [
                {"property": "Fecha", "date": {"on_or_after": inicio}},
                {"property": "Fecha", "date": {"on_or_before": fin}},
            ]
        },
        "page_size": 200,
    }
    data = notion_query(NOTION_DB_FINANZAS, body)
    resultados = data.get("results", [])
    total_ingresos = 0.0
    total_gastos = 0.0
    for page in resultados:
        props = page.get("properties", {})
        tipo = (props.get("Tipo", {}).get("select", {}) or {}).get("name", "")
        monto = props.get("Monto", {}).get("number", 0) or 0
        if tipo == "Ingreso":
            total_ingresos += monto
        elif tipo == "Egreso":
            total_gastos += monto
    balance = total_ingresos - total_gastos
    return (
        "*Resumen financiero del mes actual*\n\n"
        f"• Ingresos: `{total_ingresos:,.2f}`\n"
        f"• Gastos: `{total_gastos:,.2f}`\n"
        f"• Balance: `{balance:,.2f}`"
    )


def listar_tareas_hoy():
    hoy = hoy_iso()
    body = {
        "filter": {
            "and": [
                {"property": "Fecha", "date": {"on_or_before": hoy}},
                {"property": "Estado", "select": {"does_not_equal": "Completada"}},
            ]
        },
        "sorts": [{"property": "Fecha", "direction": "ascending"}],
        "page_size": 50,
    }
    data = notion_query(NOTION_DB_TAREAS, body)
    resultados = data.get("results", [])
    if not resultados:
        return "No tienes tareas pendientes para hoy. 😌"
    lineas = ["*Tareas para hoy / atrasadas:*"]
    for page in resultados:
        props = page.get("properties", {})
        titulo = props.get("Tarea", {}).get("title", [])
        nombre = titulo[0]["plain_text"] if titulo else "Tarea sin nombre"
        fecha = (props.get("Fecha", {}).get("date", {}) or {}).get("start", "sin fecha")
        estado = (props.get("Estado", {}).get("select", {}) or {}).get("name", "")
        prioridad = (props.get("Prioridad", {}).get("select", {}) or {}).get("name", "")
        lineas.append(f"• *{nombre}* — `{fecha}` — {estado} ({prioridad})")
    return "\n".join(lineas)


def listar_eventos_hoy_y_proximos(dias=3):
    hoy = datetime.date.today()
    fin = hoy + datetime.timedelta(days=dias)
    body = {
        "filter": {
            "and": [
                {"property": "Fecha", "date": {"on_or_after": hoy.isoformat()}},
                {"property": "Fecha", "date": {"on_or_before": fin.isoformat()}},
            ]
        },
        "sorts": [{"property": "Fecha", "direction": "ascending"}],
        "page_size": 50,
    }
    data = notion_query(NOTION_DB_EVENTOS, body)
    resultados = data.get("results", [])
    if not resultados:
        return f"No tienes eventos hoy ni en los próximos {dias} días. 🙂"
    lineas = [f"*Eventos hoy y próximos {dias} días:*"]
    for page in resultados:
        props = page.get("properties", {})
        titulo = props.get("Evento", {}).get("title", [])
        nombre = titulo[0]["plain_text"] if titulo else "Evento sin nombre"
        fecha = (props.get("Fecha", {}).get("date", {}) or {}).get("start", "sin fecha")
        lugar_rich = props.get("Lugar", {}).get("rich_text", [])
        lugar = lugar_rich[0]["plain_text"] if lugar_rich else ""
        lineas.append(f"• *{nombre}* — `{fecha}`" + (f" — {lugar}" if lugar else ""))
    return "\n".join(lineas)


def listar_proyectos_activos(limit=10):
    body = {
        "filter": {"property": "Estado", "select": {"equals": "Activo"}},
        "sorts": [{"property": "Impacto", "direction": "descending"}],
        "page_size": limit,
    }
    data = notion_query(NOTION_DB_PROYECTOS, body)
    resultados = data.get("results", [])
    if not resultados:
        return "No tienes proyectos activos."
    lineas = ["*Proyectos activos:*"]
    for page in resultados:
        props = page.get("properties", {})
        titulo = props.get("Proyecto", {}).get("title", [])
        nombre = titulo[0]["plain_text"] if titulo else "Proyecto sin nombre"
        area = (props.get("Área", {}).get("select", {}) or {}).get("name", "")
        impacto = (props.get("Impacto", {}).get("select", {}) or {}).get("name", "")
        lineas.append(f"- {nombre} ({area}, impacto {impacto})")
    return "\n".join(lineas)


def listar_habitos_activos(limit=20):
    if not NOTION_DB_HABITOS:
        return "No tengo conectada la base de hábitos."
    body = {
        "filter": {"property": "Estado", "select": {"equals": "Activo"}},
        "page_size": limit,
    }
    data = notion_query(NOTION_DB_HABITOS, body)
    resultados = data.get("results", [])
    if not resultados:
        return "No tienes hábitos activos registrados."
    lineas = ["*Hábitos activos:*"]
    for page in resultados:
        props = page.get("properties", {})
        titulo = props.get("Hábito", {}).get("title", [])
        nombre = titulo[0]["plain_text"] if titulo else "Hábito sin nombre"
        numero = props.get("Número", {}).get("number", 0) or 0
        lineas.append(f"- {nombre} (número: {numero})")
    return "\n".join(lineas)


def snapshot_contexto():
    try:
        resumen_fin = resumen_finanzas_mes()
    except Exception:
        resumen_fin = "No se pudo obtener el resumen financiero."
    try:
        tareas = listar_tareas_hoy()
    except Exception:
        tareas = "No se pudieron obtener las tareas."
    try:
        eventos = listar_eventos_hoy_y_proximos(3)
    except Exception:
        eventos = "No se pudieron obtener los eventos."
    try:
        proyectos = listar_proyectos_activos(10)
    except Exception:
        proyectos = "No se pudieron obtener los proyectos."
    try:
        habitos = listar_habitos_activos(10)
    except Exception:
        habitos = "No se pudieron obtener los hábitos."
    contexto = (
        "=== RESUMEN AUTOMÁTICO ARES1409 ===\n\n"
        f"{resumen_fin}\n\n"
        f"{tareas}\n\n"
        f"{eventos}\n\n"
        f"{proyectos}\n\n"
        f"{habitos}\n"
        "=== FIN DEL RESUMEN ==="
    )
    return contexto


# =========================
#  IA – PERSONALIDAD ARES
# =========================

def consultar_ia(mensaje_usuario):
    contexto = snapshot_contexto()
    prompt = (
        "Eres *Ares*, una asistente personal femenina, profesional, amable, "
        "organizada y muy eficiente. Hablas SIEMPRE en español. Tu tono es de "
        "secretaria ejecutiva personal: educada, clara, respetuosa y cercana, "
        "con un estilo cálido pero profesional.\n\n"
        "Tu objetivo es ayudar a Manuel a gestionar sus finanzas, tareas, "
        "eventos, proyectos y hábitos, usando la información disponible del "
        "sistema (Notion). Cuando sea útil, haz referencia explícita a los "
        "números y datos del resumen (ingresos, gastos, tareas, eventos, etc.), "
        "pero responde en texto natural, no solo listas.\n\n"
        "No eres sumisa, pero sí muy servicial y diligente. Evitas repetir "
        "la misma explicación varias veces y vas al punto.\n\n"
        "A continuación tienes un resumen reciente del sistema:\n\n"
        f"{contexto}\n\n"
        "Con base en esos datos, responde a la pregunta o petición de Manuel. "
        "Si te pide que planifiques el día o la semana, usa sus tareas y "
        "eventos. Si te pide análisis financiero, apóyate en el resumen del mes "
        "y en los últimos movimientos. Si te pide algo que requiera más datos, "
        "pregunta solo lo mínimo necesario.\n\n"
        f"Mensaje de Manuel: {mensaje_usuario}\n\n"
        "Respuesta de Ares:"
    )
    try:
        completion = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
        )
        # API Responses nueva
        try:
            return completion.output[0].content[0].text
        except Exception:
            pass
        # Propiedad de conveniencia
        try:
            return completion.output_text
        except Exception:
            pass
        return "Lo siento Manuel, hubo un problema interpretando la respuesta de la IA."
    except Exception as e:
        print("Error llamando a OpenAI:", e)
        return (
            "No pude consultar la IA en este momento. "
            "Revisa tu cuota de OpenAI o vuelve a intentarlo más tarde."
        )


# =========================
#  PARSEO DE COMANDOS
# =========================

HELP_TEXT = (
    "*Ares1409 – Comandos rápidos*\n\n"
    "• `gasto: 150 tacos`\n"
    "• `ingreso: 9000 sueldo`\n"
    "• `tarea: llamar a proveedor mañana`\n"
    "• `evento: junta kaizen viernes 16:00`\n"
    "• `proyecto: LoopMX segunda mano`\n"
    "• `hábito: leer 20 minutos`\n\n"
    "*Consultas rápidas*\n"
    "• `estado finanzas`\n"
    "• `ingresos este mes` o `ingresos`\n"
    "• `gastos este mes`\n"
    "• `tareas hoy`\n"
    "• `eventos hoy`\n"
    "• `proyectos activos`\n"
    "• `hábitos activos`\n\n"
    "Si escribes algo más libre, Ares usará la IA para ayudarte."
)


def manejar_comando_finanzas(texto, chat_id):
    if texto.startswith("gasto:"):
        contenido = texto.replace("gasto:", "", 1).strip()
        partes = contenido.split(" ", 1)
        if not partes:
            send_message(chat_id, "Formato: `gasto: 150 tacos`")
            return True
        monto = partes[0].replace(",", "")
        descripcion = partes[1] if len(partes) > 1 else "Sin descripción"
        try:
            monto_num = float(monto)
        except ValueError:
            send_message(chat_id, "No entendí el monto. Usa algo como: `gasto: 150 tacos`")
            return True
        create_financial_record(movimiento=descripcion, tipo="Egreso", monto=monto_num)
        send_message(chat_id, f"✔ Gasto registrado: {monto_num} – {descripcion}")
        return True

    if texto.startswith("ingreso:"):
        contenido = texto.replace("ingreso:", "", 1).strip()
        partes = contenido.split(" ", 1)
        if not partes:
            send_message(chat_id, "Formato: `ingreso: 9000 sueldo`")
            return True
        monto = partes[0].replace(",", "")
        descripcion = partes[1] if len(partes) > 1 else "Sin descripción"
        try:
            monto_num = float(monto)
        except ValueError:
            send_message(chat_id, "No entendí el monto. Usa algo como: `ingreso: 9000 sueldo`")
            return True
        create_financial_record(movimiento=descripcion, tipo="Ingreso", monto=monto_num)
        send_message(chat_id, f"✔ Ingreso registrado: {monto_num} – {descripcion}")
        return True

    if "estado finanzas" in texto or "balance este mes" in texto:
        send_message(chat_id, resumen_finanzas_mes())
        return True

    if "ingresos este mes" in texto or texto == "ingresos":
        send_message(chat_id, resumen_finanzas_mes())
        return True

    if "gastos este mes" in texto or texto == "gastos":
        send_message(chat_id, resumen_finanzas_mes())
        return True

    return False


def manejar_comando_tareas(texto, chat_id):
    if texto.startswith("tarea:"):
        descripcion = texto.replace("tarea:", "", 1).strip()
        if not descripcion:
            send_message(chat_id, "Formato: `tarea: descripción de la tarea`")
            return True
        create_task(descripcion)
        send_message(chat_id, f"✔ Tarea creada: {descripcion}")
        return True

    if "tareas hoy" in texto or "tareas atrasadas" in texto:
        send_message(chat_id, listar_tareas_hoy())
        return True

    return False


def manejar_comando_eventos(texto, chat_id):
    if texto.startswith("evento:"):
        descripcion = texto.replace("evento:", "", 1).strip()
        if not descripcion:
            send_message(chat_id, "Formato rápido: `evento: junta kaizen viernes 16:00`")
            return True
        create_event(descripcion, fecha=hoy_iso())
        send_message(chat_id, f"✔ Evento creado (hoy): {descripcion}")
        return True

    if "eventos hoy" in texto or "agenda" in texto:
        send_message(chat_id, listar_eventos_hoy_y_proximos(3))
        return True

    return False


def manejar_comando_proyectos(texto, chat_id):
    if texto.startswith("proyecto:"):
        nombre = texto.replace("proyecto:", "", 1).strip()
        if not nombre:
            send_message(chat_id, "Formato: `proyecto: nombre del proyecto`")
            return True
        create_project(nombre)
        send_message(chat_id, f"✔ Proyecto creado: {nombre}")
        return True

    if "proyectos activos" in texto:
        send_message(chat_id, listar_proyectos_activos(20))
        return True

    return False


def manejar_comando_habitos(texto, chat_id):
    if texto.startswith("hábito:") or texto.startswith("habito:"):
        nombre = texto.split(":", 1)[1].strip()
        if not nombre:
            send_message(chat_id, "Formato: `hábito: descripción del hábito`")
            return True
        create_habit(nombre)
        send_message(chat_id, f"✔ Hábito creado: {nombre}")
        return True

    if "hábitos activos" in texto or "habitos activos" in texto:
        send_message(chat_id, listar_habitos_activos(20))
        return True

    return False


# =========================
#  WEBHOOK TELEGRAM
# =========================

@app.route("/", methods=["GET"])
def home():
    return "Ares1409 webhook OK", 200


@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    print("Update:", json.dumps(data, ensure_ascii=False))

    message = data.get("message") or data.get("edited_message")
    if not message:
        return "OK"

    chat_id = message["chat"]["id"]
    message_id = message.get("message_id")
    text = (message.get("text") or "").strip()

    if not text:
        send_message(chat_id, "Solo entiendo mensajes de texto por ahora. 🙂")
        return "OK"

    lower = text.lower().strip()

    if lower in ("/start", "ayuda", "/help", "help"):
        send_message(chat_id, HELP_TEXT)
        return "OK"

    manejado = (
        manejar_comando_finanzas(lower, chat_id)
        or manejar_comando_tareas(lower, chat_id)
        or manejar_comando_eventos(lower, chat_id)
        or manejar_comando_proyectos(lower, chat_id)
        or manejar_comando_habitos(lower, chat_id)
    )

    if manejado:
        return "OK"

    respuesta_ia = consultar_ia(text)
    send_message(chat_id, respuesta_ia, reply_to=message_id)

    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
