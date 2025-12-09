import os
import json
import requests
import datetime
from flask import Flask, request
from openai import OpenAI

# =====================================================
#  CONFIGURACIÓN BÁSICA
# =====================================================

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
TELEGRAM_ANSWER_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
TELEGRAM_FILE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile"
TELEGRAM_FILE_BASE = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/"

NOTION_BASE_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

client = OpenAI(api_key=OPENAI_API_KEY)

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": NOTION_VERSION,
}

# Sesiones simples en memoria: {chat_id: {mode, step, data, date_field}}
SESSIONS = {}

# =====================================================
#  UTILIDADES TELEGRAM
# =====================================================

def send_message(chat_id, text, reply_to=None, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(TELEGRAM_URL, json=payload, timeout=15)
    except Exception as e:
        print("Error enviando mensaje a Telegram:", e)


def answer_callback(callback_id):
    if not callback_id:
        return
    try:
        requests.post(
            TELEGRAM_ANSWER_URL,
            json={"callback_query_id": callback_id},
            timeout=10,
        )
    except Exception as e:
        print("Error respondiendo callback:", e)


def main_menu_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "💸 Nuevo gasto", "callback_data": "menu_nuevo_gasto"},
                {"text": "💰 Nuevo ingreso", "callback_data": "menu_nuevo_ingreso"},
            ],
            [
                {"text": "✅ Nueva tarea", "callback_data": "menu_nueva_tarea"},
                {"text": "📅 Nuevo evento", "callback_data": "menu_nuevo_evento"},
            ],
            [
                {"text": "📂 Nuevo proyecto", "callback_data": "menu_nuevo_proyecto"},
                {"text": "🔁 Nuevo hábito", "callback_data": "menu_nuevo_habito"},
            ],
            [
                {"text": "📊 Resumen finanzas", "callback_data": "menu_resumen_finanzas"},
                {"text": "📋 Resumen general", "callback_data": "menu_resumen_general"},
            ],
        ]
    }


def send_main_menu(chat_id):
    texto = (
        "*Ares1409 – Panel principal*\n\n"
        "Pulsa un botón para crear o consultar información.\n"
        "En cualquier momento puedes escribir `/cancel` para cancelar el flujo actual."
    )
    send_message(chat_id, texto, reply_markup=main_menu_keyboard())

# =====================================================
#  UTILIDADES NOTION
# =====================================================

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

# =====================================================
#  FECHAS
# =====================================================

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


def date_choice_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "Hoy", "callback_data": "fecha_hoy"},
                {"text": "Mañana", "callback_data": "fecha_manana"},
                {"text": "Ayer", "callback_data": "fecha_ayer"},
            ],
            [
                {"text": "Escribir fecha (AAAA-MM-DD)", "callback_data": "fecha_manual"},
            ],
        ]
    }


def fecha_from_choice(choice):
    hoy = datetime.date.today()
    if choice == "fecha_hoy":
        return hoy
    if choice == "fecha_manana":
        return hoy + datetime.timedelta(days=1)
    if choice == "fecha_ayer":
        return hoy - datetime.timedelta(days=1)
    return None

# =====================================================
#  CREACIÓN DE REGISTROS – TABLAS
# =====================================================

def create_financial_record(
    movimiento,
    tipo,
    monto,
    categoria="General",
    area="Finanzas personales",
    fecha=None,
    metodo=None,
    notas="",
):
    if fecha is None:
        fecha = hoy_iso()
    properties = {
        "Movimiento": {"title": [{"text": {"content": movimiento}}]},
        "Tipo": {"select": {"name": tipo}},
        "Monto": {"number": float(monto)},
        "Categoría": {"select": {"name": categoria}},
        "Area": {"select": {"name": area}},
        "Fecha": {"date": {"start": fecha}},
    }
    if metodo:
        properties["Método"] = {"select": {"name": metodo}}
    if notas:
        properties["Notas"] = {"rich_text": [{"text": {"content": notas[:1800]}}]}
    notion_create_page(NOTION_DB_FINANZAS, properties)


def create_task(
    nombre,
    fecha=None,
    area="General",
    estado="Pendiente",
    prioridad="Media",
    contexto="General",
    notas="",
):
    if fecha is None:
        fecha = hoy_iso()
    properties = {
        "Tarea": {"title": [{"text": {"content": nombre}}]},
        "Estado": {"select": {"name": estado}},
        "Area": {"select": {"name": area}},
        "Fecha": {"date": {"start": fecha}},
        "Prioridad": {"select": {"name": prioridad}},
        "Contexto": {"select": {"name": contexto}},
    }
    if notas:
        properties["Notas"] = {"rich_text": [{"text": {"content": notas[:1800]}}]}
    notion_create_page(NOTION_DB_TAREAS, properties)


def create_event(
    nombre,
    fecha,
    area="General",
    tipo_evento="General",
    lugar="",
    notas="",
):
    properties = {
        "Evento": {"title": [{"text": {"content": nombre}}]},
        "Fecha": {"date": {"start": fecha}},
        "Area": {"select": {"name": area}},
        "Tipo de Evento": {"select": {"name": tipo_evento}},
    }
    if lugar:
        properties["Lugar"] = {"rich_text": [{"text": {"content": lugar[:500]}}]}
    if notas:
        properties["Notas"] = {"rich_text": [{"text": {"content": notas[:1800]}}]}
    notion_create_page(NOTION_DB_EVENTOS, properties)


def create_project(
    nombre,
    area="General",
    estado="Activo",
    fecha_inicio=None,
    fecha_fin=None,
    impacto="Medio",
    notas="",
):
    if fecha_inicio is None:
        fecha_inicio = hoy_iso()
    properties = {
        "Proyecto": {"title": [{"text": {"content": nombre}}]},
        "Area": {"select": {"name": area}},
        "Estado": {"select": {"name": estado}},
        "Fecha Inicio": {"date": {"start": fecha_inicio}},
        "Impacto": {"select": {"name": impacto}},
    }
    if fecha_fin:
        properties["Fecha objetivo fin"] = {"date": {"start": fecha_fin}}
    if notas:
        properties["Notas"] = {"rich_text": [{"text": {"content": notas[:1800]}}]}
    notion_create_page(NOTION_DB_PROYECTOS, properties)


def create_habit(nombre, area="General", estado="Activo", numero=1, notas=""):
    properties = {
        "Hábito": {"title": [{"text": {"content": nombre}}]},
        "Area": {"select": {"name": area}},
        "Estado": {"select": {"name": estado}},
        "Número": {"number": int(numero)},
    }
    if notas:
        properties["Notas"] = {"rich_text": [{"text": {"content": notas[:1800]}}]}
    notion_create_page(NOTION_DB_HABITOS, properties)

# =====================================================
#  INFORMES – RESÚMENES
# =====================================================

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
        area = (props.get("Area", {}).get("select", {}) or {}).get("name", "")
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

# =====================================================
#  IA – PERSONALIDAD ARES
# =====================================================

def consultar_ia(mensaje_usuario):
    contexto = snapshot_contexto()
    prompt = (
        "Eres *Ares*, una asistente personal femenina, profesional, amable, organizada y muy eficiente. "
        "Hablas SIEMPRE en español. Tu tono es de secretaria ejecutiva personal: educada, clara, respetuosa y cercana, "
        "con un estilo cálido pero profesional. No des discursos largos, ve al punto.\n\n"
        "Tu objetivo es ayudar a Manuel a gestionar sus finanzas, tareas, eventos, proyectos y hábitos, "
        "usando la información disponible del sistema (Notion). Cuando sea útil, haz referencia explícita "
        "a los números y datos del resumen (ingresos, gastos, tareas, eventos, etc.), pero responde en texto natural.\n\n"
        "Evita repetir la misma explicación y no ofrezcas listas de cosas en las que puedes ayudar; "
        "limítate a responder a lo que Manuel pida.\n\n"
        "A continuación tienes un resumen reciente del sistema:\n\n"
        f"{contexto}\n\n"
        "Con base en esos datos, responde a la pregunta o petición de Manuel. "
        "Si te pide que planifiques el día o la semana, usa sus tareas y eventos. "
        "Si te pide análisis financiero, apóyate en el resumen del mes y en los últimos movimientos. "
        "Si necesitas más datos, pregunta solo lo mínimo necesario.\n\n"
        f"Mensaje de Manuel: {mensaje_usuario}\n\n"
        "Respuesta de Ares:"
    )
    try:
        completion = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
        )
        text = ""
        try:
            text = completion.output[0].content[0].text
        except Exception:
            pass
        if not text:
            try:
                text = completion.output_text
            except Exception:
                text = ""
        if not text:
            text = "Lo siento Manuel, hubo un problema interpretando la respuesta de la IA."
        return text
    except Exception as e:
        print("Error llamando a OpenAI:", e)
        return (
            "No pude consultar la IA en este momento. "
            "Revisa tu cuota de OpenAI o vuelve a intentarlo más tarde."
        )

# =====================================================
#  IMÁGENES: FOTO → OCR → NOTION
# =====================================================

def get_telegram_file_url(file_id):
    try:
        r = requests.get(TELEGRAM_FILE_URL, params={"file_id": file_id}, timeout=15)
        data = r.json()
        if not data.get("ok"):
            print("Error getFile Telegram:", data)
            return None
        file_path = data["result"]["file_path"]
        return TELEGRAM_FILE_BASE + file_path
    except Exception as e:
        print("Error obteniendo archivo de Telegram:", e)
        return None


def procesar_imagen_notas(image_url):
    system_prompt = (
        "Eres una asistente que lee apuntes escritos en una imagen y los convierte "
        "en información estructurada para finanzas, tareas, eventos, proyectos y hábitos.\n\n"
        "Devuelve SIEMPRE un JSON válido con exactamente esta estructura:\n\n"
        "{\n"
        '  "finanzas": [\n'
        '    {"tipo": "Ingreso" o "Egreso", "monto": número, "descripcion": "texto"}\n'
        "  ],\n"
        '  "tareas": [\n'
        '    {"titulo": "texto de la tarea", "fecha": "YYYY-MM-DD" o null}\n'
        "  ],\n"
        '  "eventos": [\n'
        '    {"titulo": "texto del evento", "fecha": "YYYY-MM-DD" o null, "lugar": "texto o null"}\n'
        "  ],\n"
        '  "proyectos": [\n'
        '    {"nombre": "nombre del proyecto"}\n'
        "  ],\n"
        '  "habitos": [\n'
        '    {"nombre": "nombre del hábito"}\n'
        "  ]\n"
        "}\n\n"
        "Si algún apartado no aparece en los apuntes, devuélvelo como lista vacía."
    )

    user_prompt = (
        "Lee cuidadosamente los apuntes de la imagen y extrae cualquier gasto, ingreso, "
        "tarea, evento, proyecto o hábito que encuentres. No expliques nada, solo regresa el JSON."
    )

    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_prompt},
                        {"type": "input_image", "image_url": {"url": image_url}},
                    ],
                },
            ],
        )

        text = ""
        try:
            text = resp.output[0].content[0].text
        except Exception:
            pass
        if not text:
            try:
                text = resp.output_text
            except Exception:
                text = ""
        text = text.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]
        data = json.loads(text)
        return data
    except Exception as e:
        print("Error procesando imagen con OpenAI:", e)
        return {}


def guardar_notas_estructuradas(desde_imagen):
    for mov in desde_imagen.get("finanzas", []):
        try:
            tipo = mov.get("tipo", "Egreso")
            monto = float(mov.get("monto", 0))
            desc = mov.get("descripcion") or "Sin descripción"
            if monto != 0:
                create_financial_record(desc, tipo=tipo, monto=monto)
        except Exception as e:
            print("Error guardando movimiento desde imagen:", e)

    for t in desde_imagen.get("tareas", []):
        titulo = t.get("titulo") or "Tarea sin título"
        fecha = t.get("fecha") or None
        create_task(titulo, fecha=fecha)

    for ev in desde_imagen.get("eventos", []):
        titulo = ev.get("titulo") or "Evento sin título"
        fecha = ev.get("fecha") or hoy_iso()
        lugar = ev.get("lugar") or ""
        create_event(titulo, fecha=fecha, lugar=lugar)

    for p in desde_imagen.get("proyectos", []):
        nombre = p.get("nombre") or "Proyecto sin nombre"
        create_project(nombre)

    for h in desde_imagen.get("habitos", []):
        nombre = h.get("nombre") or "Hábito sin nombre"
        create_habit(nombre)

# =====================================================
#  BOTONES – OPCIONES FIJAS PARA SELECTS
# =====================================================

FIN_CATS = [
    ("Comida", "COMIDA"),
    ("Transporte", "TRANSPORTE"),
    ("Deudas", "DEUDAS"),
    ("Servicios", "SERVICIOS"),
    ("Compras", "COMPRAS"),
    ("Otros", "OTROS"),
]

FIN_METODOS = [
    ("Efectivo", "EFECTIVO"),
    ("Tarjeta crédito", "TARJETA_CREDITO"),
    ("Tarjeta débito", "TARJETA_DEBITO"),
    ("Transferencia", "TRANSFERENCIA"),
    ("Otro", "OTRO"),
]

AREAS = [
    ("General", "GENERAL"),
    ("Trabajo", "TRABAJO"),
    ("Universidad", "UNIVERSIDAD"),
    ("Casa", "CASA"),
    ("Finanzas", "FINANZAS"),
    ("Salud", "SALUD"),
]

PRIORIDADES = [
    ("Alta", "ALTA"),
    ("Media", "MEDIA"),
    ("Baja", "BAJA"),
]

CONTEXTOS = [
    ("General", "GENERAL"),
    ("PC", "PC"),
    ("Teléfono", "TELEFONO"),
    ("Casa", "CASA"),
    ("Trabajo", "TRABAJO"),
]

TIPOS_EVENTO = [
    ("Reunión", "REUNION"),
    ("Personal", "PERSONAL"),
    ("Estudio", "ESTUDIO"),
    ("Recordatorio", "RECORDATORIO"),
    ("Otro", "OTRO"),
]

IMPACTOS = [
    ("Alto", "ALTO"),
    ("Medio", "MEDIO"),
    ("Bajo", "BAJO"),
]

def simple_inline_keyboard(prefix, items):
    # items: list of (label, token)
    row = []
    kb = []
    for label, token in items:
        row.append({"text": label, "callback_data": f"{prefix}{token}"})
        if len(row) == 3:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    return {"inline_keyboard": kb}

# =====================================================
#  MANEJO DE ESTADO (SESIONES)
# =====================================================

def reset_session(chat_id):
    if chat_id in SESSIONS:
        del SESSIONS[chat_id]


def start_flow(chat_id, mode):
    SESSIONS[chat_id] = {
        "mode": mode,
        "step": None,
        "data": {},
        "date_field": None,
    }

# =====================================================
#  FLUJOS POR TEXTO (SEGÚN STEP)
# =====================================================

def handle_state_message(chat_id, text):
    """
    Maneja mensajes de texto cuando hay un flujo activo en SESSIONS[chat_id].
    Devuelve True si el mensaje se usó en el flujo, False si no.
    """
    session = SESSIONS.get(chat_id)
    if not session:
        return False

    mode = session["mode"]
    step = session["step"]

    # Para fechas manuales (todos los modos)
    if step == "awaiting_date_manual":
        try:
            dt = datetime.datetime.strptime(text.strip(), "%Y-%m-%d").date()
            session["data"][session["date_field"]] = dt.isoformat()
        except ValueError:
            send_message(chat_id, "Fecha no válida. Usa el formato `AAAA-MM-DD`.")
            return True
        # seguimos al siguiente paso según modo
        if mode in ("gasto", "ingreso"):
            finalizar_gasto_ingreso(chat_id)
        elif mode == "tarea":
            session["step"] = "area_tarea"
            send_message(
                chat_id,
                "¿En qué *área* está esta tarea?",
                reply_markup=simple_inline_keyboard("area_", AREAS),
            )
        elif mode == "evento":
            session["step"] = "area_evento"
            send_message(
                chat_id,
                "¿En qué *área* está este evento?",
                reply_markup=simple_inline_keyboard("area_", AREAS),
            )
        elif mode == "proyecto" and session["date_field"] == "fecha_inicio":
            session["step"] = "pregunta_fecha_fin"
            send_message(
                chat_id,
                "¿Quieres agregar una *fecha objetivo fin*?",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {"text": "Sí", "callback_data": "proy_fecha_fin_si"},
                            {"text": "No", "callback_data": "proy_fecha_fin_no"},
                        ]
                    ]
                },
            )
        elif mode == "proyecto" and session["date_field"] == "fecha_fin":
            finalizar_proyecto(chat_id)
        else:
            # otros casos no deberían ocurrir
            reset_session(chat_id)
            send_message(chat_id, "Flujo finalizado.")
        return True

    # ------------------------ GASTO / INGRESO ------------------------
    if mode in ("gasto", "ingreso"):
        if step == "monto":
            try:
                monto = float(text.replace(",", ""))
            except ValueError:
                send_message(chat_id, "No entendí el monto. Escribe solo el número, por ejemplo `250`.")
                return True
            session["data"]["monto"] = monto
            session["step"] = "descripcion"
            send_message(chat_id, "Perfecto. Ahora dime una breve *descripción* (ej. gasolina Clio).")
            return True

        if step == "descripcion":
            session["data"]["descripcion"] = text.strip() or "Sin descripción"
            session["step"] = "categoria"
            send_message(
                chat_id,
                "Elige la *categoría*:",
                reply_markup=simple_inline_keyboard("fin_cat_", FIN_CATS),
            )
            return True

        if step == "notas_fin":
            notas = text.strip()
            if notas == "-":
                notas = ""
            session["data"]["notas"] = notas
            session["step"] = "fecha"
            session["date_field"] = "fecha"
            send_message(
                chat_id,
                "¿Qué *fecha* quieres usar para este movimiento?",
                reply_markup=date_choice_keyboard(),
            )
            return True

    # ------------------------ TAREA ------------------------
    if mode == "tarea":
        if step == "titulo_tarea":
            session["data"]["titulo"] = text.strip()
            session["step"] = "fecha_tarea"
            session["date_field"] = "fecha"
            send_message(
                chat_id,
                "¿Para qué *fecha* es esta tarea?",
                reply_markup=date_choice_keyboard(),
            )
            return True

        if step == "notas_tarea":
            notas = text.strip()
            if notas == "-":
                notas = ""
            session["data"]["notas"] = notas
            finalizar_tarea(chat_id)
            return True

    # ------------------------ EVENTO ------------------------
    if mode == "evento":
        if step == "titulo_evento":
            session["data"]["titulo"] = text.strip()
            session["step"] = "fecha_evento"
            session["date_field"] = "fecha"
            send_message(
                chat_id,
                "¿Qué *fecha* tendrá este evento?",
                reply_markup=date_choice_keyboard(),
            )
            return True

        if step == "lugar_evento":
            lugar = text.strip()
            if lugar == "-":
                lugar = ""
            session["data"]["lugar"] = lugar
            session["step"] = "notas_evento"
            send_message(
                chat_id,
                "Si quieres, escribe unas *notas* para este evento.\n"
                "Si no, responde con `-`.",
            )
            return True

        if step == "notas_evento":
            notas = text.strip()
            if notas == "-":
                notas = ""
            session["data"]["notas"] = notas
            finalizar_evento(chat_id)
            return True

    # ------------------------ PROYECTO ------------------------
    if mode == "proyecto":
        if step == "titulo_proyecto":
            session["data"]["titulo"] = text.strip()
            session["step"] = "area_proyecto"
            send_message(
                chat_id,
                "¿En qué *área* está este proyecto?",
                reply_markup=simple_inline_keyboard("area_", AREAS),
            )
            return True

        if step == "notas_proyecto":
            notas = text.strip()
            if notas == "-":
                notas = ""
            session["data"]["notas"] = notas
            finalizar_proyecto(chat_id)
            return True

    # ------------------------ HÁBITO ------------------------
    if mode == "habito":
        if step == "titulo_habito":
            session["data"]["titulo"] = text.strip()
            session["step"] = "area_habito"
            send_message(
                chat_id,
                "¿En qué *área* se ubica este hábito?",
                reply_markup=simple_inline_keyboard("area_", AREAS),
            )
            return True

        if step == "numero_habito":
            try:
                numero = int(text.strip())
            except ValueError:
                send_message(chat_id, "Escribe un número entero (ej. `1`, `2`, `3`).")
                return True
            session["data"]["numero"] = numero
            session["step"] = "notas_habito"
            send_message(
                chat_id,
                "Si quieres, escribe unas *notas* para este hábito.\n"
                "Si no, responde con `-`.",
            )
            return True

        if step == "notas_habito":
            notas = text.strip()
            if notas == "-":
                notas = ""
            session["data"]["notas"] = notas
            finalizar_habito(chat_id)
            return True

    return False

# =====================================================
#  FINALIZADORES DE FLUJO
# =====================================================

def finalizar_gasto_ingreso(chat_id):
    session = SESSIONS.get(chat_id)
    if not session:
        return
    data = session["data"]
    tipo = "Egreso" if session["mode"] == "gasto" else "Ingreso"
    monto = data.get("monto")
    desc = data.get("descripcion", "")
    categoria = data.get("categoria", "General")
    metodo = data.get("metodo")
    notas = data.get("notas", "")
    fecha = data.get("fecha", hoy_iso())

    create_financial_record(
        movimiento=desc,
        tipo=tipo,
        monto=monto,
        categoria=categoria,
        metodo=metodo,
        notas=notas,
        fecha=fecha,
    )
    reset_session(chat_id)
    send_message(
        chat_id,
        f"✔ {tipo} registrado: `{monto}` – {desc}\nCategoría: {categoria}, Método: {metodo or 'N/A'}.",
    )
    send_main_menu(chat_id)


def finalizar_tarea(chat_id):
    session = SESSIONS.get(chat_id)
    if not session:
        return
    d = session["data"]
    create_task(
        nombre=d.get("titulo", "Tarea sin título"),
        fecha=d.get("fecha", hoy_iso()),
        area=d.get("area", "General"),
        estado="Pendiente",
        prioridad=d.get("prioridad", "Media"),
        contexto=d.get("contexto", "General"),
        notas=d.get("notas", ""),
    )
    reset_session(chat_id)
    send_message(chat_id, "✔ Tarea creada correctamente.")
    send_main_menu(chat_id)


def finalizar_evento(chat_id):
    session = SESSIONS.get(chat_id)
    if not session:
        return
    d = session["data"]
    create_event(
        nombre=d.get("titulo", "Evento sin título"),
        fecha=d.get("fecha", hoy_iso()),
        area=d.get("area", "General"),
        tipo_evento=d.get("tipo_evento", "General"),
        lugar=d.get("lugar", ""),
        notas=d.get("notas", ""),
    )
    reset_session(chat_id)
    send_message(chat_id, "✔ Evento creado correctamente.")
    send_main_menu(chat_id)


def finalizar_proyecto(chat_id):
    session = SESSIONS.get(chat_id)
    if not session:
        return
    d = session["data"]
    create_project(
        nombre=d.get("titulo", "Proyecto sin título"),
        area=d.get("area", "General"),
        estado="Activo",
        fecha_inicio=d.get("fecha_inicio", hoy_iso()),
        fecha_fin=d.get("fecha_fin"),
        impacto=d.get("impacto", "Medio"),
        notas=d.get("notas", ""),
    )
    reset_session(chat_id)
    send_message(chat_id, "✔ Proyecto creado correctamente.")
    send_main_menu(chat_id)


def finalizar_habito(chat_id):
    session = SESSIONS.get(chat_id)
    if not session:
        return
    d = session["data"]
    create_habit(
        nombre=d.get("titulo", "Hábito sin título"),
        area=d.get("area", "General"),
        estado="Activo",
        numero=d.get("numero", 1),
        notas=d.get("notas", ""),
    )
    reset_session(chat_id)
    send_message(chat_id, "✔ Hábito creado correctamente.")
    send_main_menu(chat_id)

# =====================================================
#  MANEJO DE CALLBACKS (BOTONES)
# =====================================================

def handle_callback(chat_id, callback_id, data):
    answer_callback(callback_id)

    # Menú principal
    if data == "menu_nuevo_gasto":
        start_flow(chat_id, "gasto")
        SESSIONS[chat_id]["step"] = "monto"
        send_message(chat_id, "Vamos a registrar un *gasto*.\n\nPrimero, escribe el *monto* (solo número).")
        return

    if data == "menu_nuevo_ingreso":
        start_flow(chat_id, "ingreso")
        SESSIONS[chat_id]["step"] = "monto"
        send_message(chat_id, "Vamos a registrar un *ingreso*.\n\nPrimero, escribe el *monto* (solo número).")
        return

    if data == "menu_nueva_tarea":
        start_flow(chat_id, "tarea")
        SESSIONS[chat_id]["step"] = "titulo_tarea"
        send_message(chat_id, "Escribe el *título* de la tarea.")
        return

    if data == "menu_nuevo_evento":
        start_flow(chat_id, "evento")
        SESSIONS[chat_id]["step"] = "titulo_evento"
        send_message(chat_id, "Escribe el *nombre* del evento.")
        return

    if data == "menu_nuevo_proyecto":
        start_flow(chat_id, "proyecto")
        SESSIONS[chat_id]["step"] = "titulo_proyecto"
        send_message(chat_id, "Escribe el *nombre* del proyecto.")
        return

    if data == "menu_nuevo_habito":
        start_flow(chat_id, "habito")
        SESSIONS[chat_id]["step"] = "titulo_habito"
        send_message(chat_id, "Escribe el *nombre* del hábito.")
        return

    if data == "menu_resumen_finanzas":
        send_message(chat_id, resumen_finanzas_mes())
        return

    if data == "menu_resumen_general":
        send_message(chat_id, snapshot_contexto())
        return

    # Si hay sesión activa, seguimos
    session = SESSIONS.get(chat_id)
    if not session:
        return

    mode = session["mode"]
    step = session["step"]

    # ------------------------ FECHAS (GENÉRICO) ------------------------
    if data in ("fecha_hoy", "fecha_manana", "fecha_ayer"):
        dt = fecha_from_choice(data)
        if not dt:
            return
        field = session.get("date_field", "fecha")
        session["data"][field] = dt.isoformat()

        if mode in ("gasto", "ingreso"):
            finalizar_gasto_ingreso(chat_id)
        elif mode == "tarea":
            session["step"] = "area_tarea"
            send_message(
                chat_id,
                "¿En qué *área* está esta tarea?",
                reply_markup=simple_inline_keyboard("area_", AREAS),
            )
        elif mode == "evento":
            session["step"] = "area_evento"
            send_message(
                chat_id,
                "¿En qué *área* está este evento?",
                reply_markup=simple_inline_keyboard("area_", AREAS),
            )
        elif mode == "proyecto" and field == "fecha_inicio":
            session["step"] = "pregunta_fecha_fin"
            send_message(
                chat_id,
                "¿Quieres agregar una *fecha objetivo fin*?",
                reply_markup={
                    "inline_keyboard": [
                        [
                            {"text": "Sí", "callback_data": "proy_fecha_fin_si"},
                            {"text": "No", "callback_data": "proy_fecha_fin_no"},
                        ]
                    ]
                },
            )
        elif mode == "proyecto" and field == "fecha_fin":
            finalizar_proyecto(chat_id)
        return

    if data == "fecha_manual":
        session["step"] = "awaiting_date_manual"
        send_message(chat_id, "Escribe la fecha en formato `AAAA-MM-DD`.")
        return

    # ------------------------ CATEGORÍA / MÉTODO (FINANZAS) ------------------------
    if data.startswith("fin_cat_") and mode in ("gasto", "ingreso"):
        token = data.replace("fin_cat_", "")
        # Convertimos token a label simple
        nombre = token.replace("_", " ").title()
        session["data"]["categoria"] = nombre
        session["step"] = "metodo"
        send_message(
            chat_id,
            "¿Qué *método de pago* usaste?",
            reply_markup=simple_inline_keyboard("fin_met_", FIN_METODOS),
        )
        return

    if data.startswith("fin_met_") and mode in ("gasto", "ingreso"):
        token = data.replace("fin_met_", "")
        nombre = token.replace("_", " ").title()
        session["data"]["metodo"] = nombre
        session["step"] = "notas_fin"
        send_message(
            chat_id,
            "Si quieres, escribe unas *notas* (ej. a meses sin intereses, deuda X).\n"
            "Si no, responde con `-`.",
        )
        return

    # ------------------------ ÁREAS ------------------------
    if data.startswith("area_"):
        token = data.replace("area_", "")
        area = token.capitalize()
        if mode == "tarea" and step == "area_tarea":
            session["data"]["area"] = area
            session["step"] = "prioridad_tarea"
            send_message(
                chat_id,
                "Elige la *prioridad* de la tarea:",
                reply_markup=simple_inline_keyboard("prio_", PRIORIDADES),
            )
            return
        if mode == "evento" and step == "area_evento":
            session["data"]["area"] = area
            session["step"] = "tipo_evento"
            send_message(
                chat_id,
                "Elige el *tipo de evento*:",
                reply_markup=simple_inline_keyboard("tipoev_", TIPOS_EVENTO),
            )
            return
        if mode == "proyecto" and step == "area_proyecto":
            session["data"]["area"] = area
            session["step"] = "impacto_proyecto"
            send_message(
                chat_id,
                "Elige el *impacto* del proyecto:",
                reply_markup=simple_inline_keyboard("imp_", IMPACTOS),
            )
            return
        if mode == "habito" and step == "area_habito":
            session["data"]["area"] = area
            session["step"] = "numero_habito"
            send_message(
                chat_id,
                "¿Qué *número* usarás para este hábito? (ej. 1 vez/día, 3 veces/semana, etc.)\n"
                "Escribe solo el número.",
            )
            return

    # ------------------------ PRIORIDAD / CONTEXTO (TAREAS) ------------------------
    if data.startswith("prio_") and mode == "tarea":
        token = data.replace("prio_", "")
        prioridad = token.capitalize()
        session["data"]["prioridad"] = prioridad
        session["step"] = "contexto_tarea"
        send_message(
            chat_id,
            "Elige el *contexto* de la tarea:",
            reply_markup=simple_inline_keyboard("ctx_", CONTEXTOS),
        )
        return

    if data.startswith("ctx_") and mode == "tarea":
        token = data.replace("ctx_", "")
        contexto = token.capitalize()
        session["data"]["contexto"] = contexto
        session["step"] = "notas_tarea"
        send_message(
            chat_id,
            "Si quieres, escribe unas *notas* para esta tarea.\n"
            "Si no, responde con `-`.",
        )
        return

    # ------------------------ EVENTOS ------------------------
    if data.startswith("tipoev_") and mode == "evento":
        token = data.replace("tipoev_", "")
        tipo = token.capitalize()
        session["data"]["tipo_evento"] = tipo
        session["step"] = "lugar_evento"
        send_message(
            chat_id,
            "¿En qué *lugar* será el evento?\n"
            "Si no quieres especificar, responde con `-`.",
        )
        return

    # ------------------------ PROYECTOS ------------------------
    if data.startswith("imp_") and mode == "proyecto":
        token = data.replace("imp_", "")
        impacto = token.capitalize()
        session["data"]["impacto"] = impacto
        session["step"] = "fecha_inicio_proyecto"
        session["date_field"] = "fecha_inicio"
        send_message(
            chat_id,
            "¿Cuál será la *fecha de inicio* del proyecto?",
            reply_markup=date_choice_keyboard(),
        )
        return

    if data == "proy_fecha_fin_si" and mode == "proyecto":
        session["step"] = "fecha_fin_proyecto"
        session["date_field"] = "fecha_fin"
        send_message(
            chat_id,
            "Elige la *fecha objetivo fin* del proyecto:",
            reply_markup=date_choice_keyboard(),
        )
        return

    if data == "proy_fecha_fin_no" and mode == "proyecto":
        session["data"]["fecha_fin"] = None
        session["step"] = "notas_proyecto"
        send_message(
            chat_id,
            "Si quieres, escribe unas *notas* para el proyecto.\n"
            "Si no, responde con `-`.",
        )
        return

# =====================================================
#  PARSEO RÁPIDO DE COMANDOS (TEXTO)
# =====================================================

HELP_TEXT = (
    "*Ares1409 – Comandos rápidos*\n\n"
    "Puedes usar los *botones del menú* para flujos guiados.\n\n"
    "También tienes comandos de texto:\n"
    "• `gasto: 150 tacos`\n"
    "• `ingreso: 9000 sueldo`\n"
    "• `tarea: llamar a proveedor mañana` (se crea con valores por defecto)\n\n"
    "Y puedes escribir cualquier cosa para hablar con Ares usando IA."
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
        create_financial_record(
            movimiento=descripcion,
            tipo="Egreso",
            monto=monto_num,
        )
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
        create_financial_record(
            movimiento=descripcion,
            tipo="Ingreso",
            monto=monto_num,
        )
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
    if "eventos hoy" in texto or "agenda" in texto:
        send_message(chat_id, listar_eventos_hoy_y_proximos(3))
        return True
    return False


def manejar_comando_proyectos(texto, chat_id):
    if "proyectos activos" in texto:
        send_message(chat_id, listar_proyectos_activos(20))
        return True
    return False


def manejar_comando_habitos(texto, chat_id):
    if "hábitos activos" in texto or "habitos activos" in texto:
        send_message(chat_id, listar_habitos_activos(20))
        return True
    return False

# =====================================================
#  WEBHOOK TELEGRAM
# =====================================================

@app.route("/", methods=["GET"])
def home():
    return "Ares1409 webhook OK", 200


@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(force=True, silent=True) or {}
    print("Update:", json.dumps(data, ensure_ascii=False))

    # 1) CALLBACKS DE BOTONES
    callback = data.get("callback_query")
    if callback:
        chat_id = callback["message"]["chat"]["id"]
        callback_id = callback.get("id")
        cb_data = callback.get("data", "")
        handle_callback(chat_id, callback_id, cb_data)
        return "OK"

    # 2) MENSAJES (TEXTO / FOTO)
    message = data.get("message") or data.get("edited_message")
    if not message:
        return "OK"

    chat_id = message["chat"]["id"]
    message_id = message.get("message_id")

    # FOTO → OCR
    if "photo" in message:
        photo_sizes = message["photo"]
        file_id = photo_sizes[-1]["file_id"]
        file_url = get_telegram_file_url(file_id)
        if not file_url:
            send_message(chat_id, "No pude descargar la imagen, intenta de nuevo por favor.")
            return "OK"

        send_message(
            chat_id,
            "Dame un momento, voy a leer tus apuntes y organizarlos en Notion…",
            reply_to=message_id,
        )
        data_notas = procesar_imagen_notas(file_url)
        if not data_notas:
            send_message(chat_id, "No pude interpretar la imagen. Intenta que la foto sea más clara.")
            return "OK"

        guardar_notas_estructuradas(data_notas)
        send_message(chat_id, "Listo, ya guardé lo que encontré en tus apuntes en Notion. ✅")
        return "OK"

    # TEXTO
    text = (message.get("text") or "").strip()
    lower = text.lower()

    if not text:
        send_message(chat_id, "Solo entiendo mensajes de texto o fotos de apuntes por ahora. 🙂")
        return "OK"

    # Cancelar flujo
    if lower in ("/cancel", "cancelar", "cancel"):
        reset_session(chat_id)
        send_message(chat_id, "Flujo cancelado. Volvemos al menú principal.")
        send_main_menu(chat_id)
        return "OK"

    # /start, ayuda, menu
    if lower in ("/start", "ayuda", "/help", "help", "menu"):
        reset_session(chat_id)
        send_main_menu(chat_id)
        return "OK"

    # Si hay un flujo activo, lo usamos primero
    if chat_id in SESSIONS:
        usado = handle_state_message(chat_id, text)
        if usado:
            return "OK"

    # Si no, probamos comandos rápidos
    manejado = (
        manejar_comando_finanzas(lower, chat_id)
        or manejar_comando_tareas(lower, chat_id)
        or manejar_comando_eventos(lower, chat_id)
        or manejar_comando_proyectos(lower, chat_id)
        or manejar_comando_habitos(lower, chat_id)
    )
    if manejado:
        return "OK"

    # Último recurso: IA
    respuesta_ia = consultar_ia(text)
    send_message(chat_id, respuesta_ia, reply_to=message_id)

    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
