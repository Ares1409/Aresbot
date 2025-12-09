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

# Teclado principal de Telegram
MAIN_KEYBOARD = {
    "keyboard": [
        ["Nueva tarea", "Nuevo evento"],
        ["Nuevo proyecto", "Nuevo hábito"],
        ["Resumen finanzas", "Resumen general"],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}

# Estado simple por chat para los botones (máquina de estados)
SESSIONS = {}

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


def mes_y_anio(fecha_iso: str):
    d = datetime.date.fromisoformat(fecha_iso)
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    return meses[d.month - 1], d.year

# =========================
#  CREACIÓN DE REGISTROS
# =========================

def create_financial_record(
    movimiento,
    tipo,
    monto,
    categoria="General",
    area="Finanzas personales",
    fecha=None,
    metodo="General",
    notas="",
):
    if fecha is None:
        fecha = hoy_iso()

    mes, anio = mes_y_anio(fecha)

    properties = {
        "Movimiento": {"title": [{"text": {"content": movimiento}}]},
        "Tipo": {"select": {"name": tipo}},          # Ingreso / Egreso
        "Monto": {"number": float(monto)},
        "Categoría": {"select": {"name": categoria}},
        "Area": {"select": {"name": area}},
        "Fecha": {"date": {"start": fecha}},
        "Método": {"select": {"name": metodo}},
        "Notas": {"rich_text": [{"text": {"content": notas[:1800]}}]} if notas else {"rich_text": []},
        "Mes": {"select": {"name": mes}},
        "Año": {"number": int(anio)},
    }
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
        "Notas": {"rich_text": [{"text": {"content": notas[:1800]}}]} if notas else {"rich_text": []},
    }
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
        "Lugar": {"rich_text": [{"text": {"content": lugar[:500]}}]} if lugar else {"rich_text": []},
        "Notas": {"rich_text": [{"text": {"content": notas[:1800]}}]} if notas else {"rich_text": []},
    }
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
        "Notas": {"rich_text": [{"text": {"content": notas[:1800]}}]} if notas else {"rich_text": []},
    }
    if fecha_fin:
        properties["Fecha objetivo fin"] = {"date": {"start": fecha_fin}}
    notion_create_page(NOTION_DB_PROYECTOS, properties)


def create_habit(
    nombre,
    area="General",
    estado="Activo",
    numero=1,
    notas="",
):
    properties = {
        "Hábito": {"title": [{"text": {"content": nombre}}]},
        "Área": {"select": {"name": area}},  # columna con acento
        "Estado": {"select": {"name": estado}},
        "Número": {"number": int(numero)},
        "Notas": {"rich_text": [{"text": {"content": notas[:1800]}}]} if notas else {"rich_text": []},
    }
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


def tareas_pendientes_por_area():
    body = {
        "filter": {"property": "Estado", "select": {"does_not_equal": "Completada"}},
        "page_size": 100,
    }
    data = notion_query(NOTION_DB_TAREAS, body)
    resultados = data.get("results", [])
    if not resultados:
        return "No tienes tareas pendientes. 😌"

    por_area = {}
    for page in resultados:
        props = page.get("properties", {})
        area = (props.get("Area", {}).get("select", {}) or {}).get("name", "Sin área")
        titulo = props.get("Tarea", {}).get("title", [])
        nombre = titulo[0]["plain_text"] if titulo else "Tarea sin nombre"
        por_area.setdefault(area, []).append(nombre)

    lineas = ["*Tareas pendientes por área:*"]
    for area, tareas in por_area.items():
        lineas.append(f"- *{area}*:")
        for t in tareas:
            lineas.append(f"  • {t}")
    return "\n".join(lineas)


def resumen_general():
    partes = []
    try:
        partes.append(resumen_finanzas_mes())
    except Exception:
        partes.append("No se pudo obtener el resumen financiero.")

    try:
        partes.append(tareas_pendientes_por_area())
    except Exception:
        partes.append("No se pudieron obtener las tareas pendientes.")

    try:
        partes.append(listar_eventos_hoy_y_proximos(7))
    except Exception:
        partes.append("No se pudieron obtener los próximos eventos.")

    try:
        partes.append(listar_proyectos_activos(20))
    except Exception:
        partes.append("No se pudieron obtener los proyectos.")
    try:
        partes.append(listar_habitos_activos(20))
    except Exception:
        partes.append("No se pudieron obtener los hábitos.")

    return "\n\n".join(partes)

# =========================
#  CONTEXTO PARA IA
# =========================

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
#  PARSEO DE COMANDOS (TEXTO PLANO)
# =========================

HELP_TEXT = (
    "*Ares1409 – Comandos rápidos*\n\n"
    "Botones disponibles en el teclado:\n"
    "• Nueva tarea\n"
    "• Nuevo evento\n"
    "• Nuevo proyecto\n"
    "• Nuevo hábito\n"
    "• Resumen finanzas\n"
    "• Resumen general\n\n"
    "También puedes usar texto libre y Ares usará IA para ayudarte."
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
        send_message(
            chat_id,
            "Solo entiendo mensajes de texto o fotos de apuntes por ahora. 🙂",
            reply_markup=MAIN_KEYBOARD,
        )
        return "OK"

    lower = text.lower().strip()

    # Comandos de inicio / menú
    if lower in ("/start", "ayuda", "/help", "help", "menu", "menú"):
        send_message(
            chat_id,
            "Hola Manuel, soy Ares. Usa los botones para crear tareas, eventos, proyectos, hábitos "
            "o para ver tus resúmenes.",
            reply_markup=MAIN_KEYBOARD,
        )
        # al entrar al menú limpiamos cualquier sesión rota
        if chat_id in SESSIONS:
            del SESSIONS[chat_id]
        return "OK"

    # =========================
    #  MANEJO DE SESIONES (BOTONES)
    # =========================
    if chat_id in SESSIONS:
        session = SESSIONS[chat_id]
        mode = session.get("mode")
        step = session.get("step", 1)
        data_s = session.setdefault("data", {})
        lower_txt = lower

        # ---------- NUEVA TAREA ----------
        if mode == "new_task":
            if step == 1:
                data_s["titulo"] = text
                session["step"] = 2
                send_message(chat_id, "Área de la tarea (ejemplo: General, Trabajo, Universidad). Si no quieres especificar, escribe `General`.", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 2:
                data_s["area"] = text if text else "General"
                session["step"] = 3
                send_message(chat_id, "Fecha de la tarea en formato `AAAA-MM-DD` o escribe `hoy`.", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 3:
                if lower_txt == "hoy":
                    fecha = hoy_iso()
                else:
                    try:
                        datetime.date.fromisoformat(text)
                        fecha = text
                    except ValueError:
                        send_message(chat_id, "No entendí la fecha. Usa `AAAA-MM-DD` o `hoy`.", reply_markup=MAIN_KEYBOARD)
                        return "OK"
                data_s["fecha"] = fecha
                session["step"] = 4
                send_message(chat_id, "Prioridad de la tarea (`Baja`, `Media` o `Alta`). Si dudas, escribe `Media`.", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 4:
                prioridad = text.capitalize()
                if prioridad not in ("Baja", "Media", "Alta"):
                    prioridad = "Media"
                data_s["prioridad"] = prioridad
                session["step"] = 5
                send_message(chat_id, "Contexto de la tarea (ejemplo: PC, Teléfono, Casa). Si no necesitas, escribe `General`.", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 5:
                data_s["contexto"] = text if text else "General"
                session["step"] = 6
                send_message(chat_id, "Notas adicionales para la tarea (o escribe `no` si no quieres notas).", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 6:
                notas = "" if lower_txt in ("no", "ninguna", "ninguno") else text
                data_s["notas"] = notas

                create_task(
                    nombre=data_s["titulo"],
                    fecha=data_s["fecha"],
                    area=data_s["area"],
                    estado="Pendiente",
                    prioridad=data_s["prioridad"],
                    contexto=data_s["contexto"],
                    notas=data_s["notas"],
                )
                send_message(chat_id, f"✔ Tarea creada:\n*{data_s['titulo']}* ({data_s['area']}, prioridad {data_s['prioridad']})", reply_markup=MAIN_KEYBOARD)
                del SESSIONS[chat_id]
                return "OK"

        # ---------- NUEVO PROYECTO ----------
        if mode == "new_project":
            if step == 1:
                data_s["nombre"] = text
                session["step"] = 2
                send_message(chat_id, "Área del proyecto (ejemplo: Trabajo, Universidad, Personal). Usa el nombre tal cual lo tengas en Notion, por ejemplo `General`.", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 2:
                data_s["area"] = text if text else "General"
                session["step"] = 3
                send_message(chat_id, "Estado del proyecto (`Activo`, `Pausado`, `Completado`). Si dudas, `Activo`.", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 3:
                estado = text.capitalize() if text else "Activo"
                if estado not in ("Activo", "Pausado", "Completado"):
                    estado = "Activo"
                data_s["estado"] = estado
                session["step"] = 4
                send_message(chat_id, "Fecha de inicio (`AAAA-MM-DD` o `hoy`).", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 4:
                if lower_txt == "hoy":
                    fecha_inicio = hoy_iso()
                else:
                    try:
                        datetime.date.fromisoformat(text)
                        fecha_inicio = text
                    except ValueError:
                        send_message(chat_id, "No entendí la fecha. Usa `AAAA-MM-DD` o `hoy`.", reply_markup=MAIN_KEYBOARD)
                        return "OK"
                data_s["fecha_inicio"] = fecha_inicio
                session["step"] = 5
                send_message(chat_id, "Fecha objetivo de fin (`AAAA-MM-DD`) o escribe `ninguna` si aún no está definida.", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 5:
                if lower_txt in ("ninguna", "ninguno", "no"):
                    fecha_fin = None
                else:
                    try:
                        datetime.date.fromisoformat(text)
                        fecha_fin = text
                    except ValueError:
                        send_message(chat_id, "No entendí la fecha. Usa `AAAA-MM-DD` o `ninguna`.", reply_markup=MAIN_KEYBOARD)
                        return "OK"
                data_s["fecha_fin"] = fecha_fin
                session["step"] = 6
                send_message(chat_id, "Impacto del proyecto (`Bajo`, `Medio`, `Alto`). Si dudas, `Medio`.", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 6:
                impacto = text.capitalize() if text else "Medio"
                if impacto not in ("Bajo", "Medio", "Alto"):
                    impacto = "Medio"
                data_s["impacto"] = impacto
                session["step"] = 7
                send_message(chat_id, "Notas del proyecto (o escribe `no` si no quieres notas).", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 7:
                notas = "" if lower_txt in ("no", "ninguna", "ninguno") else text
                data_s["notas"] = notas

                create_project(
                    nombre=data_s["nombre"],
                    area=data_s["area"],
                    estado=data_s["estado"],
                    fecha_inicio=data_s["fecha_inicio"],
                    fecha_fin=data_s["fecha_fin"],
                    impacto=data_s["impacto"],
                    notas=data_s["notas"],
                )
                send_message(chat_id, f"✔ Proyecto creado:\n*{data_s['nombre']}* ({data_s['area']}, impacto {data_s['impacto']})", reply_markup=MAIN_KEYBOARD)
                del SESSIONS[chat_id]
                return "OK"

        # ---------- NUEVO HÁBITO ----------
        if mode == "new_habit":
            if step == 1:
                data_s["nombre"] = text
                session["step"] = 2
                send_message(chat_id, "Área del hábito (ejemplo: Salud, Estudio, Finanzas, General).", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 2:
                data_s["area"] = text if text else "General"
                session["step"] = 3
                send_message(chat_id, "Número asociado al hábito (veces al día, pomodoros, etc.). Escribe un número entero, por ejemplo `1` o `3`.", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 3:
                try:
                    numero = int(text)
                except ValueError:
                    numero = 1
                data_s["numero"] = numero
                session["step"] = 4
                send_message(chat_id, "Notas del hábito (o escribe `no` si no quieres notas).", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 4:
                notas = "" if lower_txt in ("no", "ninguna", "ninguno") else text
                data_s["notas"] = notas

                create_habit(
                    nombre=data_s["nombre"],
                    area=data_s["area"],
                    estado="Activo",
                    numero=data_s["numero"],
                    notas=data_s["notas"],
                )
                send_message(chat_id, f"✔ Hábito creado:\n*{data_s['nombre']}* ({data_s['area']}, número {data_s['numero']})", reply_markup=MAIN_KEYBOARD)
                del SESSIONS[chat_id]
                return "OK"

        # ---------- NUEVO EVENTO ----------
        if mode == "new_event":
            if step == 1:
                data_s["titulo"] = text
                session["step"] = 2
                send_message(chat_id, "Fecha del evento (`AAAA-MM-DD` o `hoy`).", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 2:
                if lower_txt == "hoy":
                    fecha = hoy_iso()
                else:
                    try:
                        datetime.date.fromisoformat(text)
                        fecha = text
                    except ValueError:
                        send_message(chat_id, "No entendí la fecha. Usa `AAAA-MM-DD` o `hoy`.", reply_markup=MAIN_KEYBOARD)
                        return "OK"
                data_s["fecha"] = fecha
                session["step"] = 3
                send_message(chat_id, "Área del evento (ejemplo: Trabajo, Personal, Universidad, General).", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 3:
                data_s["area"] = text if text else "General"
                session["step"] = 4
                send_message(chat_id, "Tipo de evento (ejemplo: Reunión, Personal, Estudio, General).", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 4:
                data_s["tipo_evento"] = text if text else "General"
                session["step"] = 5
                send_message(chat_id, "Lugar del evento (o escribe `ninguno` si es en línea o no aplica).", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 5:
                lugar = "" if lower_txt in ("ninguno", "ninguna", "no") else text
                data_s["lugar"] = lugar
                session["step"] = 6
                send_message(chat_id, "Notas del evento (o escribe `no` si no quieres notas).", reply_markup=MAIN_KEYBOARD)
                return "OK"
            elif step == 6:
                notas = "" if lower_txt in ("no", "ninguna", "ninguno") else text
                data_s["notas"] = notas

                create_event(
                    nombre=data_s["titulo"],
                    fecha=data_s["fecha"],
                    area=data_s["area"],
                    tipo_evento=data_s["tipo_evento"],
                    lugar=data_s["lugar"],
                    notas=data_s["notas"],
                )
                send_message(chat_id, f"✔ Evento creado:\n*{data_s['titulo']}* el {data_s['fecha']} ({data_s['area']})", reply_markup=MAIN_KEYBOARD)
                del SESSIONS[chat_id]
                return "OK"

    # =========================
    #  INICIO DE SESIONES DESDE BOTONES
    # =========================
    if lower == "nueva tarea":
        SESSIONS[chat_id] = {"mode": "new_task", "step": 1, "data": {}}
        send_message(chat_id, "Escribe la descripción de la nueva tarea.", reply_markup=MAIN_KEYBOARD)
        return "OK"

    if lower == "nuevo proyecto":
        SESSIONS[chat_id] = {"mode": "new_project", "step": 1, "data": {}}
        send_message(chat_id, "Escribe el nombre del nuevo proyecto.", reply_markup=MAIN_KEYBOARD)
        return "OK"

    if lower in ("nuevo hábito", "nuevo habito"):
        SESSIONS[chat_id] = {"mode": "new_habit", "step": 1, "data": {}}
        send_message(chat_id, "Escribe el nombre del nuevo hábito.", reply_markup=MAIN_KEYBOARD)
        return "OK"

    if lower == "nuevo evento":
        SESSIONS[chat_id] = {"mode": "new_event", "step": 1, "data": {}}
        send_message(chat_id, "Dime el título del evento (por ejemplo: reunión con gerencia).", reply_markup=MAIN_KEYBOARD)
        return "OK"

    if lower in ("resumen finanzas", "resumen de gastos e ingresos"):
        send_message(chat_id, resumen_finanzas_mes(), reply_markup=MAIN_KEYBOARD)
        return "OK"

    if lower == "resumen general":
        send_message(chat_id, resumen_general(), reply_markup=MAIN_KEYBOARD)
        return "OK"

    # =========================
    #  COMANDOS TIPO TEXTO
    # =========================
    manejado = (
        manejar_comando_finanzas(lower, chat_id)
        or manejar_comando_tareas(lower, chat_id)
        or manejar_comando_eventos(lower, chat_id)
        or manejar_comando_proyectos(lower, chat_id)
        or manejar_comando_habitos(lower, chat_id)
    )

    if manejado:
        return "OK"

    # =========================
    #  IA POR DEFECTO
    # =========================
    respuesta_ia = consultar_ia(text)
    send_message(chat_id, respuesta_ia, reply_to=message_id, reply_markup=MAIN_KEYBOARD)

    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
