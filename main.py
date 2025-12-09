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

# Estado de conversaciones (para asistentes paso a paso)
conversation_state = {}

# =========================
#  UTILIDADES BÁSICAS
# =========================

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


def build_main_keyboard():
    return {
        "keyboard": [
            [{"text": "➕ Gasto"}, {"text": "➕ Ingreso"}],
            [{"text": "➕ Tarea"}, {"text": "➕ Evento"}],
            [{"text": "Estado finanzas"}, {"text": "Tareas hoy"}, {"text": "Eventos hoy"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


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


def parse_fecha_simple(texto):
    """
    Acepta: 'hoy', 'mañana', 'manana', '2025-12-12', '12/12/2025', '12-12-2025', etc.
    Devuelve fecha en formato YYYY-MM-DD o None si no se puede interpretar.
    """
    texto = (texto or "").strip().lower()
    hoy = datetime.date.today()
    if texto in ("hoy", "today"):
        return hoy.isoformat()
    if texto in ("mañana", "manana", "tomorrow"):
        return (hoy + datetime.timedelta(days=1)).isoformat()

    # intentar YYYY-MM-DD
    try:
        return datetime.date.fromisoformat(texto).isoformat()
    except Exception:
        pass

    # intentar DD/MM/YYYY o DD-MM-YYYY
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.datetime.strptime(texto, fmt).date().isoformat()
        except Exception:
            continue

    return None

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
        "Area": {"select": {"name": area}},
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
        "Area": {"select": {"name": area}},
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
        "Area": {"select": {"name": area}},
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


def create_habit(nombre, area="General", estado="Activo",
                 numero=1, notas=""):
    properties = {
        "Hábito": {"title": [{"text": {"content": nombre}}]},
        "Area": {"select": {"name": area}},
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

# =========================
#  IA – PERSONALIDAD ARES
# =========================

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

# =========================
#  IMÁGENES: FOTO → OCR → NOTION
# =========================

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
        '    {"titulo": "texto de la tarea', "fecha": "YYYY-MM-DD" o null}\n"
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
    # Finanzas
    for mov in desde_imagen.get("finanzas", []):
        try:
            tipo = mov.get("tipo", "Egreso")
            monto = float(mov.get("monto", 0))
            desc = mov.get("descripcion") or "Sin descripción"
            if monto != 0:
                create_financial_record(desc, tipo=tipo, monto=monto)
        except Exception as e:
            print("Error guardando movimiento desde imagen:", e)

    # Tareas
    for t in desde_imagen.get("tareas", []):
        titulo = t.get("titulo") or "Tarea sin título"
        fecha = t.get("fecha") or None
        create_task(titulo, fecha=fecha)

    # Eventos
    for ev in desde_imagen.get("eventos", []):
        titulo = ev.get("titulo") or "Evento sin título"
        fecha = ev.get("fecha") or hoy_iso()
        lugar = ev.get("lugar") or ""
        create_event(titulo, fecha=fecha, lugar=lugar)

    # Proyectos
    for p in desde_imagen.get("proyectos", []):
        nombre = p.get("nombre") or "Proyecto sin nombre"
        create_project(nombre)

    # Hábitos
    for h in desde_imagen.get("habitos", []):
        nombre = h.get("nombre") or "Hábito sin nombre"
        create_habit(nombre)

# =========================
#  CONVERSACIONES GUIADAS (EVENTOS)
# =========================

def iniciar_creacion_evento(chat_id):
    conversation_state[chat_id] = {
        "modo": "crear_evento",
        "paso": "titulo",
        "temp": {},
    }
    send_message(
        chat_id,
        "Vamos a crear un evento nuevo.\n\nDime el *título* del evento:",
        reply_markup=build_main_keyboard(),
    )


def manejar_conversacion(chat_id, text):
    estado = conversation_state.get(chat_id)
    if not estado:
        return False

    modo = estado.get("modo")
    paso = estado.get("paso")

    if modo == "crear_evento":
        if paso == "titulo":
            estado["temp"]["titulo"] = text.strip()
            estado["paso"] = "fecha"
            send_message(
                chat_id,
                "Perfecto. ¿Para qué *fecha* es el evento?\n"
                "Puedes escribir: `hoy`, `mañana` o una fecha como `2025-12-12` o `12/12/2025`.",
            )
            return True

        if paso == "fecha":
            fecha = parse_fecha_simple(text)
            if not fecha:
                send_message(
                    chat_id,
                    "No entendí la fecha. Escríbela como `2025-12-12`, `12/12/2025` "
                    "o pon `hoy` / `mañana`.",
                )
                return True
            estado["temp"]["fecha"] = fecha
            estado["paso"] = "lugar"
            send_message(
                chat_id,
                "¿En qué *lugar* será el evento?\n"
                "Si no quieres especificar lugar, escribe `-`.",
            )
            return True

        if paso == "lugar":
            lugar = text.strip()
            if lugar == "-":
                lugar = ""
            titulo = estado["temp"].get("titulo", "Evento sin título")
            fecha = estado["temp"].get("fecha", hoy_iso())
            create_event(titulo, fecha=fecha, lugar=lugar)
            conversation_state.pop(chat_id, None)
            send_message(
                chat_id,
                f"✔ Evento creado: *{titulo}* — `{fecha}`" + (f" — {lugar}" if lugar else ""),
                reply_markup=build_main_keyboard(),
            )
            return True

    return False

# =========================
#  PARSEO DE COMANDOS
# =========================

HELP_TEXT = (
    "*Ares1409 – Comandos rápidos*\n\n"
    "También puedes usar los botones del teclado.\n\n"
    "• `gasto: 150 tacos`\n"
    "• `ingreso: 9000 sueldo`\n"
    "• `tarea: llamar a proveedor mañana`\n"
    "• `evento: junta kaizen viernes 16:00` (modo simple, todo va en el título)\n"
    "• `proyecto: LoopMX segunda mano`\n"
    "• `hábito: leer 20 minutos`\n\n"
    "*Consultas rápidas*\n"
    "• `estado finanzas`\n"
    "• `ingresos este mes` o `ingresos`\n"
    "• `gastos este mes` o `gastos`\n"
    "• `tareas hoy`\n"
    "• `eventos hoy`\n"
    "• `proyectos activos`\n"
    "• `hábitos activos`\n\n"
    "Para crear eventos bien estructurados, usa el botón `➕ Evento`."
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
        # aquí sigue modo simple: todo va en el título y la fecha es hoy
        create_event(descripcion, fecha=hoy_iso())
        send_message(chat_id, f"✔ Evento creado (hoy): {descripcion}")
        return True

    if "eventos hoy" in texto or "agenda" in texto:
        send_message(chat_id, listar_eventos_hoy_y_proximos(3))
        return True

    # comandos tipo "nuevo evento" disparan el flujo guiado
    if "nuevo evento" in texto or "crear evento" in texto:
        iniciar_creacion_evento(chat_id)
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

    # FOTO → OCR → NOTION
    if "photo" in message:
        photo_sizes = message["photo"]
        file_id = photo_sizes[-1]["file_id"]  # mayor resolución
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
    if not text:
        send_message(chat_id, "Solo entiendo mensajes de texto o fotos de apuntes por ahora. 🙂")
        return "OK"

    # ¿Estamos en una conversación guiada?
    if manejar_conversacion(chat_id, text):
        return "OK"

    lower = text.lower().strip()

    # /start o menú
    if lower in ("/start", "start", "ayuda", "/help", "help", "menu", "menú"):
        send_message(
            chat_id,
            "Hola Manuel, soy Ares. Aquí tienes el menú principal y algunos ejemplos de comandos.\n\n"
            + HELP_TEXT,
            reply_markup=build_main_keyboard(),
        )
        return "OK"

    # Botones directos
    if text == "➕ Evento":
        iniciar_creacion_evento(chat_id)
        return "OK"

    if text == "➕ Tarea":
        send_message(chat_id, "Escribe la tarea con el formato: `tarea: descripción de la tarea`.")
        return "OK"

    if text == "➕ Gasto":
        send_message(chat_id, "Escribe el gasto con el formato: `gasto: 150 tacos`.")
        return "OK"

    if text == "➕ Ingreso":
        send_message(chat_id, "Escribe el ingreso con el formato: `ingreso: 9000 sueldo`.")
        return "OK"

    if lower == "estado finanzas":
        send_message(chat_id, resumen_finanzas_mes())
        return "OK"

    if lower == "tareas hoy":
        send_message(chat_id, listar_tareas_hoy())
        return "OK"

    if lower == "eventos hoy":
        send_message(chat_id, listar_eventos_hoy_y_proximos(3))
        return "OK"

    # Comandos de texto clásicos
    manejado = (
        manejar_comando_finanzas(lower, chat_id)
        or manejar_comando_tareas(lower, chat_id)
        or manejar_comando_eventos(lower, chat_id)
        or manejar_comando_proyectos(lower, chat_id)
        or manejar_comando_habitos(lower, chat_id)
    )

    if manejado:
        return "OK"

    # IA por defecto
    respuesta_ia = consultar_ia(text)
    send_message(chat_id, respuesta_ia, reply_to=message_id)

    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
