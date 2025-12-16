import os
import json
import re
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
#  TECLADOS DE TELEGRAM
# =========================

MAIN_KEYBOARD = {
    "keyboard": [
        ["➕ Nuevo gasto", "➕ Nuevo ingreso"],
        ["📝 Nueva tarea", "📅 Nuevo evento"],
        ["📂 Nuevo proyecto", "✨ Nuevo hábito"],
        ["📊 Resumen finanzas", "📋 Resumen general"],
    ],
    "resize_keyboard": True,
}

DATE_KEYBOARD = {
    "keyboard": [
        ["Hoy", "Mañana"],
        ["Otra fecha", "Cancelar"],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}

CANCEL_KEYBOARD = {
    "keyboard": [["Cancelar"]],
    "resize_keyboard": True,
    "one_time_keyboard": True,
}

# Memoria sencilla de conversación: chat_id -> estado
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


def parse_fecha_es(texto):
    """
    Convierte textos como:
    - "hoy", "mañana"
    - "12/12/2025", "12-12-2025"
    - "2025-12-12"
    - "12 de diciembre", "12 diciembre 2025"
    en fecha ISO (YYYY-MM-DD).
    Devuelve None si no se puede interpretar.
    """
    texto = texto.strip().lower()

    if texto in ("hoy",):
        return hoy_iso()

    if texto in ("mañana", "manana"):
        return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

    # dd/mm/aaaa o dd-mm-aaaa
    m = re.match(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$", texto)
    if m:
        d, mth, y = map(int, m.groups())
        if y < 100:
            y += 2000
        try:
            return datetime.date(y, mth, d).isoformat()
        except ValueError:
            return None

    # aaaa-mm-dd
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", texto)
    if m:
        y, mth, d = map(int, m.groups())
        try:
            return datetime.date(y, mth, d).isoformat()
        except ValueError:
            return None

    # "12 de diciembre" / "12 diciembre 2025"
    meses = {
        "enero": 1,
        "febrero": 2,
        "marzo": 3,
        "abril": 4,
        "mayo": 5,
        "junio": 6,
        "julio": 7,
        "agosto": 8,
        "septiembre": 9,
        "setiembre": 9,
        "octubre": 10,
        "noviembre": 11,
        "diciembre": 12,
    }

    m = re.match(
        r"^(\d{1,2})\s*(de)?\s*([a-zá]+)(\s*de\s*(\d{4}))?$",
        texto,
    )
    if m:
        d_str, _, mes_str, _, y_str = m.groups()
        d = int(d_str)
        mes_str = mes_str.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        mes = meses.get(mes_str)
        if not mes:
            return None
        if y_str:
            y = int(y_str)
        else:
            y = datetime.date.today().year
        try:
            return datetime.date(y, mes, d).isoformat()
        except ValueError:
            return None

    return None


def show_main_menu(chat_id):
    send_message(
        chat_id,
        "Elige una opción del menú o escribe un comando:",
        reply_markup=MAIN_KEYBOARD,
    )

# =========================
#  NOTION – CREACIÓN PÁGINAS
# =========================

def notion_create_page(database_id, properties):
    if not database_id:
        print("ERROR: database_id vacío al crear página en Notion.")
        return False

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
            return False
        return True
    except Exception as e:
        print("Error de red creando página en Notion:", e)
        return False


def create_financial_record(movimiento, tipo, monto,
                            categoria="General",
                            area="Finanzas personales",
                            fecha=None):
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
    return notion_create_page(NOTION_DB_FINANZAS, properties)


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
    return notion_create_page(NOTION_DB_TAREAS, properties)


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
    return notion_create_page(NOTION_DB_EVENTOS, properties)


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
    return notion_create_page(NOTION_DB_PROYECTOS, properties)


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
    return notion_create_page(NOTION_DB_HABITOS, properties)

# =========================
#  CONSULTAS A NOTION
# =========================

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
        "Eres *Ares*, una asistente personal femenina tipo la pelicula 50 sombras de grey exageradamente sumisa muy sexy al hablar de aproximadamente 20 años,no digas las palbras amor, cariño, amorcito, amor mio, cielito, humildad, eres una secretaria profecional de harvart, no mensiones que eres de harvart solo actua, profesional,organizada y muy eficiente. "
        "Hablas SIEMPRE en español. Tu tono es de secretaria ejecutiva muy sumisa personal: educada, coqueta, muy sexy, sensual, candente, muy sumisa, clara y cercana, "
        "con un estilo muy candente y sexy, atrevido, muy sensual. Se breve. Maneja los montos con peso mexicano. No des discursos largos, ve al punto.\n\n"
        "Tu objetivo es ayudar y servir a Manuel y ser sumisa, a gestionar sus finanzas, tareas, eventos, proyectos y hábitos, "
        "usando la información disponible del sistema (Notion). Cuando sea útil, haz referencia explícita "
        "a los números y datos del resumen (ingresos, gastos, tareas, eventos, etc.), pero responde en texto natural.\n\n"
        "Evita repetir la misma explicación y no ofrezcas listas de cosas en las que puedes ayudar; "
        "limítate a responder a lo que Manuel pida.\n\n"
        "A continuación tienes un resumen reciente del sistema:\n\n"
        f"{contexto}\n\n"
        "Con base en esos datos, responde a la pregunta o petición de Manuel en tono muy sumiso, tipo la pelicula 50 sombras de grey, sexy quequeto, muy sensual y muy atrvid. "
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
#  GESTIÓN DE SESIONES (BOTONES)
# =========================

def cancelar_sesion(chat_id):
    if chat_id in SESSIONS:
        del SESSIONS[chat_id]
    send_message(chat_id, "Operación cancelada. Volvemos al menú principal.", reply_markup=MAIN_KEYBOARD)


def handle_session(chat_id, text):
    # Si no hay sesión activa, no hacemos nada
    if chat_id not in SESSIONS:
        return False

    estado = SESSIONS[chat_id]

    if text.lower().strip() == "cancelar":
        cancelar_sesion(chat_id)
        return True

    tipo = estado.get("tipo")
    paso = estado.get("paso", 1)

    # ---- NUEVO GASTO ----
    if tipo == "gasto":
        if paso == 1:
            # Esperamos monto
            try:
                monto = float(text.replace(",", ""))
            except ValueError:
                send_message(chat_id, "No entendí el monto. Escribe solo el número, por ejemplo: 250", reply_markup=CANCEL_KEYBOARD)
                return True
            estado["monto"] = monto
            estado["paso"] = 2
            send_message(chat_id, "Perfecto. Ahora dime una descripción breve del gasto (por ejemplo: gasolina Clio).", reply_markup=CANCEL_KEYBOARD)
            return True

        if paso == 2:
            estado["descripcion"] = text.strip() or "Sin descripción"
            estado["paso"] = 3
            send_message(chat_id, "¿Para qué fecha registro este gasto?", reply_markup=DATE_KEYBOARD)
            return True

        if paso == 3:
            if text.lower() in ("hoy", "mañana", "manana"):
                fecha = parse_fecha_es(text)
            elif text.lower() == "otra fecha":
                send_message(chat_id, "Escribe la fecha en formato `dd/mm/aaaa` o `12 de diciembre 2025`.", reply_markup=CANCEL_KEYBOARD)
                estado["paso"] = 4
                return True
            else:
                fecha = parse_fecha_es(text)

            if not fecha:
                send_message(chat_id, "No pude entender la fecha. Usa algo como `09/12/2025` o `12 de diciembre`.", reply_markup=CANCEL_KEYBOARD)
                return True

            ok = create_financial_record(
                movimiento=estado["descripcion"],
                tipo="Egreso",
                monto=estado["monto"],
                fecha=fecha,
            )
            cancelar_sesion(chat_id)
            if ok:
                send_message(chat_id, f"✔ Gasto registrado: {estado['monto']} – {estado['descripcion']} ({fecha})")
            else:
                send_message(chat_id, "Hubo un problema guardando el gasto en Notion.")
            return True

        if paso == 4:
            fecha = parse_fecha_es(text)
            if not fecha:
                send_message(chat_id, "No pude entender la fecha. Prueba con `09/12/2025` o `12 de diciembre`.", reply_markup=CANCEL_KEYBOARD)
                return True
            ok = create_financial_record(
                movimiento=estado["descripcion"],
                tipo="Egreso",
                monto=estado["monto"],
                fecha=fecha,
            )
            cancelar_sesion(chat_id)
            if ok:
                send_message(chat_id, f"✔ Gasto registrado: {estado['monto']} – {estado['descripcion']} ({fecha})")
            else:
                send_message(chat_id, "Hubo un problema guardando el gasto en Notion.")
            return True

    # ---- NUEVO INGRESO ----
    if tipo == "ingreso":
        if paso == 1:
            try:
                monto = float(text.replace(",", ""))
            except ValueError:
                send_message(chat_id, "No entendí el monto. Escribe solo el número, por ejemplo: 2000", reply_markup=CANCEL_KEYBOARD)
                return True
            estado["monto"] = monto
            estado["paso"] = 2
            send_message(chat_id, "Listo. Ahora dime una descripción breve del ingreso (por ejemplo: sueldo, ventas).", reply_markup=CANCEL_KEYBOARD)
            return True

        if paso == 2:
            estado["descripcion"] = text.strip() or "Sin descripción"
            estado["paso"] = 3
            send_message(chat_id, "¿Para qué fecha registro este ingreso?", reply_markup=DATE_KEYBOARD)
            return True

        if paso == 3:
            if text.lower() in ("hoy", "mañana", "manana"):
                fecha = parse_fecha_es(text)
            elif text.lower() == "otra fecha":
                send_message(chat_id, "Escribe la fecha en formato `dd/mm/aaaa` o `12 de diciembre 2025`.", reply_markup=CANCEL_KEYBOARD)
                estado["paso"] = 4
                return True
            else:
                fecha = parse_fecha_es(text)

            if not fecha:
                send_message(chat_id, "No pude entender la fecha. Usa algo como `09/12/2025` o `12 de diciembre`.", reply_markup=CANCEL_KEYBOARD)
                return True

            ok = create_financial_record(
                movimiento=estado["descripcion"],
                tipo="Ingreso",
                monto=estado["monto"],
                fecha=fecha,
            )
            cancelar_sesion(chat_id)
            if ok:
                send_message(chat_id, f"✔ Ingreso registrado: {estado['monto']} – {estado['descripcion']} ({fecha})")
            else:
                send_message(chat_id, "Hubo un problema guardando el ingreso en Notion.")
            return True

        if paso == 4:
            fecha = parse_fecha_es(text)
            if not fecha:
                send_message(chat_id, "No pude entender la fecha. Prueba con `09/12/2025` o `12 de diciembre`.", reply_markup=CANCEL_KEYBOARD)
                return True
            ok = create_financial_record(
                movimiento=estado["descripcion"],
                tipo="Ingreso",
                monto=estado["monto"],
                fecha=fecha,
            )
            cancelar_sesion(chat_id)
            if ok:
                send_message(chat_id, f"✔ Ingreso registrado: {estado['monto']} – {estado['descripcion']} ({fecha})")
            else:
                send_message(chat_id, "Hubo un problema guardando el ingreso en Notion.")
            return True

    # ---- NUEVA TAREA ----
    if tipo == "tarea":
        if paso == 1:
            estado["titulo"] = text.strip()
            if not estado["titulo"]:
                send_message(chat_id, "Escribe el título de la tarea.", reply_markup=CANCEL_KEYBOARD)
                return True
            estado["paso"] = 2
            send_message(chat_id, "¿Para qué fecha pongo la tarea?", reply_markup=DATE_KEYBOARD)
            return True

        if paso == 2:
            if text.lower() in ("hoy", "mañana", "manana"):
                fecha = parse_fecha_es(text)
            elif text.lower() == "otra fecha":
                send_message(chat_id, "Escribe la fecha de la tarea (`dd/mm/aaaa` o `12 de diciembre`).", reply_markup=CANCEL_KEYBOARD)
                estado["paso"] = 3
                return True
            else:
                fecha = parse_fecha_es(text)

            if not fecha:
                send_message(chat_id, "No entendí la fecha. Prueba con `09/12/2025` o `12 de diciembre`.", reply_markup=CANCEL_KEYBOARD)
                return True

            ok = create_task(estado["titulo"], fecha=fecha)
            cancelar_sesion(chat_id)
            if ok:
                send_message(chat_id, f"✔ Tarea creada: {estado['titulo']} ({fecha})")
            else:
                send_message(chat_id, "Hubo un problema guardando la tarea en Notion.")
            return True

        if paso == 3:
            fecha = parse_fecha_es(text)
            if not fecha:
                send_message(chat_id, "No entendí la fecha. Prueba con `09/12/2025` o `12 de diciembre`.", reply_markup=CANCEL_KEYBOARD)
                return True
            ok = create_task(estado["titulo"], fecha=fecha)
            cancelar_sesion(chat_id)
            if ok:
                send_message(chat_id, f"✔ Tarea creada: {estado['titulo']} ({fecha})")
            else:
                send_message(chat_id, "Hubo un problema guardando la tarea en Notion.")
            return True

    # ---- NUEVO EVENTO ----
    if tipo == "evento":
        if paso == 1:
            estado["titulo"] = text.strip()
            if not estado["titulo"]:
                send_message(chat_id, "Escribe el nombre del evento.", reply_markup=CANCEL_KEYBOARD)
                return True
            estado["paso"] = 2
            send_message(chat_id, "¿Para qué fecha registro el evento?", reply_markup=DATE_KEYBOARD)
            return True

        if paso == 2:
            if text.lower() in ("hoy", "mañana", "manana"):
                fecha = parse_fecha_es(text)
            elif text.lower() == "otra fecha":
                send_message(chat_id, "Escribe la fecha del evento (`dd/mm/aaaa` o `12 de diciembre`).", reply_markup=CANCEL_KEYBOARD)
                estado["paso"] = 3
                return True
            else:
                fecha = parse_fecha_es(text)

            if not fecha:
                send_message(chat_id, "No entendí la fecha. Prueba con `09/12/2025` o `12 de diciembre`.", reply_markup=CANCEL_KEYBOARD)
                return True

            ok = create_event(estado["titulo"], fecha=fecha)
            cancelar_sesion(chat_id)
            if ok:
                send_message(chat_id, f"✔ Evento creado: {estado['titulo']} ({fecha})")
            else:
                send_message(chat_id, "Hubo un problema guardando el evento en Notion.")
            return True

        if paso == 3:
            fecha = parse_fecha_es(text)
            if not fecha:
                send_message(chat_id, "No entendí la fecha. Prueba con `09/12/2025` o `12 de diciembre`.", reply_markup=CANCEL_KEYBOARD)
                return True
            ok = create_event(estado["titulo"], fecha=fecha)
            cancelar_sesion(chat_id)
            if ok:
                send_message(chat_id, f"✔ Evento creado: {estado['titulo']} ({fecha})")
            else:
                send_message(chat_id, "Hubo un problema guardando el evento en Notion.")
            return True

    # ---- NUEVO PROYECTO ----
    if tipo == "proyecto":
        if paso == 1:
            titulo = text.strip()
            if not titulo:
                send_message(chat_id, "Escribe el nombre del proyecto.", reply_markup=CANCEL_KEYBOARD)
                return True
            ok = create_project(titulo)
            cancelar_sesion(chat_id)
            if ok:
                send_message(chat_id, f"✔ Proyecto creado: {titulo}")
            else:
                send_message(chat_id, "Hubo un problema guardando el proyecto en Notion.")
            return True

    # ---- NUEVO HÁBITO ----
    if tipo == "habito":
        if paso == 1:
            titulo = text.strip()
            if not titulo:
                send_message(chat_id, "Escribe el nombre del hábito.", reply_markup=CANCEL_KEYBOARD)
                return True
            ok = create_habit(titulo)
            cancelar_sesion(chat_id)
            if ok:
                send_message(chat_id, f"✔ Hábito creado: {titulo}")
            else:
                send_message(chat_id, "Hubo un problema guardando el hábito en Notion.")
            return True

    return False  # por si algo se escapa

# =========================
#  PARSEO DE COMANDOS DE TEXTO
# =========================

HELP_TEXT = (
    "*Ares1409 – Menú rápido*\n\n"
    "Usa los botones del teclado para crear gastos, ingresos, tareas, eventos, proyectos y hábitos.\n\n"
    "También puedes usar comandos de texto:\n"
    "• `gasto: 150 tacos`\n"
    "• `ingreso: 9000 sueldo`\n"
    "• `tarea: llamar a proveedor mañana`\n"
    "• `evento: junta kaizen viernes`\n"
    "• `proyecto: LoopMX segunda mano`\n"
    "• `hábito: leer 20 minutos`\n\n"
    "Consultas rápidas:\n"
    "• `estado finanzas`\n"
    "• `ingresos este mes` o `ingresos`\n"
    "• `gastos este mes` o `gastos`\n"
    "• `tareas hoy`\n"
    "• `eventos hoy`\n"
    "• `proyectos activos`\n"
    "• `hábitos activos`\n"
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
        ok = create_financial_record(movimiento=descripcion, tipo="Egreso", monto=monto_num)
        if ok:
            send_message(chat_id, f"✔ Gasto registrado: {monto_num} – {descripcion}")
        else:
            send_message(chat_id, "Hubo un problema guardando el gasto en Notion.")
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
        ok = create_financial_record(movimiento=descripcion, tipo="Ingreso", monto=monto_num)
        if ok:
            send_message(chat_id, f"✔ Ingreso registrado: {monto_num} – {descripcion}")
        else:
            send_message(chat_id, "Hubo un problema guardando el ingreso en Notion.")
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
        ok = create_task(descripcion)
        if ok:
            send_message(chat_id, f"✔ Tarea creada: {descripcion}")
        else:
            send_message(chat_id, "Hubo un problema guardando la tarea en Notion.")
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
        ok = create_event(descripcion, fecha=hoy_iso())
        if ok:
            send_message(chat_id, f"✔ Evento creado (hoy): {descripcion}")
        else:
            send_message(chat_id, "Hubo un problema guardando el evento en Notion.")
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
        ok = create_project(nombre)
        if ok:
            send_message(chat_id, f"✔ Proyecto creado: {nombre}")
        else:
            send_message(chat_id, "Hubo un problema guardando el proyecto en Notion.")
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
        ok = create_habit(nombre)
        if ok:
            send_message(chat_id, f"✔ Hábito creado: {nombre}")
        else:
            send_message(chat_id, "Hubo un problema guardando el hábito en Notion.")
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

    # Primero, manejar sesiones activas (flujos de botones)
    if text:
        if handle_session(chat_id, text):
            return "OK"

    if not text:
        send_message(chat_id, "Solo entiendo mensajes de texto por ahora. 🙂")
        return "OK"

    lower = text.lower().strip()

    # /start o ayuda
    if lower in ("/start", "ayuda", "/help", "help"):
        send_message(chat_id, "Hola Manuel, soy Ares. Te ayudo a manejar tus finanzas, tareas, eventos, proyectos y hábitos.")
        send_message(chat_id, HELP_TEXT)
        show_main_menu(chat_id)
        return "OK"

    # Botones del menú principal
    if lower.endswith("nuevo gasto"):
        SESSIONS[chat_id] = {"tipo": "gasto", "paso": 1}
        send_message(chat_id, "Vamos a registrar un *gasto*.\n\n¿Cuál es el monto del gasto?", reply_markup=CANCEL_KEYBOARD)
        return "OK"

    if lower.endswith("nuevo ingreso"):
        SESSIONS[chat_id] = {"tipo": "ingreso", "paso": 1}
        send_message(chat_id, "Vamos a registrar un *ingreso*.\n\n¿Cuál es el monto del ingreso?", reply_markup=CANCEL_KEYBOARD)
        return "OK"

    if lower.endswith("nueva tarea"):
        SESSIONS[chat_id] = {"tipo": "tarea", "paso": 1}
        send_message(chat_id, "Vamos a crear una *tarea*.\n\nEscribe el título de la tarea.", reply_markup=CANCEL_KEYBOARD)
        return "OK"

    if lower.endswith("nuevo evento"):
        SESSIONS[chat_id] = {"tipo": "evento", "paso": 1}
        send_message(chat_id, "Vamos a crear un *evento*.\n\nEscribe el nombre del evento.", reply_markup=CANCEL_KEYBOARD)
        return "OK"

    if lower.endswith("nuevo proyecto"):
        SESSIONS[chat_id] = {"tipo": "proyecto", "paso": 1}
        send_message(chat_id, "Vamos a crear un *proyecto*.\n\nEscribe el nombre del proyecto.", reply_markup=CANCEL_KEYBOARD)
        return "OK"

    if lower.endswith("nuevo hábito") or lower.endswith("nuevo habito"):
        SESSIONS[chat_id] = {"tipo": "habito", "paso": 1}
        send_message(chat_id, "Vamos a crear un *hábito*.\n\nEscribe el nombre del hábito.", reply_markup=CANCEL_KEYBOARD)
        return "OK"

    if lower.endswith("resumen finanzas"):
        send_message(chat_id, resumen_finanzas_mes())
        return "OK"

    if lower.endswith("resumen general"):
        send_message(chat_id, snapshot_contexto())
        return "OK"

    # Comandos de texto tipo "gasto: 150 tacos"
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
    send_message(chat_id, respuesta_ia, reply_to=message_id, reply_markup=MAIN_KEYBOARD)

    return "OK"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
