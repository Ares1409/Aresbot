import os
import json
import requests
import datetime
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DB_FINANZAS = os.getenv("NOTION_DB_FINANZAS")

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
NOTION_URL = "https://api.notion.com/v1/pages"

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def send_message(chat_id, text):
    requests.post(TELEGRAM_URL, json={
        "chat_id": chat_id,
        "text": text
    })

def create_financial_record(movimiento, tipo, monto, categoria, fecha):
    data = {
        "parent": {"database_id": NOTION_DB_FINANZAS},
        "properties": {
            "Movimiento": {"title": [{"text": {"content": movimiento}}]},
            "Tipo": {"select": {"name": tipo}},
            "Monto": {"number": float(monto)},
            "Categoría": {"select": {"name": categoria}},
            "Área": {"select": {"name": "Finanzas personales"}},
            "Fecha": {"date": {"start": fecha}}
        }
    }
    resp = requests.post(NOTION_URL, headers=HEADERS, json=data)
    # Para depurar si algo falla
    print("NOTION STATUS:", resp.status_code, resp.text)

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "").lower().strip()

        # FORMATO: gasto: 150 tacos
        if text.startswith("gasto:"):
            contenido = text.replace("gasto:", "", 1).strip()
            partes = contenido.split(" ", 1)

            if not partes or not partes[0].replace(".", "", 1).isdigit():
                send_message(chat_id, "Formato: gasto: 150 tacos")
                return "OK"

            monto = partes[0]
            descripcion = partes[1] if len(partes) > 1 else "Sin descripción"

            hoy = datetime.date.today().isoformat()

            create_financial_record(
                movimiento=descripcion,
                tipo="Egreso",
                monto=monto,
                categoria="General",
                fecha=hoy
            )

            send_message(chat_id, f"✔ Gasto registrado: {monto} - {descripcion}")
            return "OK"

        # FORMATO: ingreso: 9000 sueldo
        if text.startswith("ingreso:"):
            contenido = text.replace("ingreso:", "", 1).strip()
            partes = contenido.split(" ", 1)

            if not partes or not partes[0].replace(".", "", 1).isdigit():
                send_message(chat_id, "Formato: ingreso: 9000 sueldo")
                return "OK"

            monto = partes[0]
            descripcion = partes[1] if len(partes) > 1 else "Sin descripción"

            hoy = datetime.date.today().isoformat()

            create_financial_record(
                movimiento=descripcion,
                tipo="Ingreso",
                monto=monto,
                categoria="General",
                fecha=hoy
            )

            send_message(chat_id, f"✔ Ingreso registrado: {monto} - {descripcion}")
            return "OK"

        # Si no es un comando reconocido
        send_message(
            chat_id,
            "No entendí el comando.\n"
            "Ejemplos:\n"
            "gasto: 150 tacos\n"
            "ingreso: 9000 sueldo"
        )

    return "OK"

@app.route("/", methods=["GET"])
def home():
    return "Ares1409 Bot Running"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
