import os
import requests
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()

    if "message" in data:
        chat_id = data["message"]["chat"]["id"]
        text = data["message"].get("text", "")

        # Respuesta básica (verificamos que el bot está vivo)
        requests.post(TELEGRAM_URL, json={
            "chat_id": chat_id,
            "text": f"Recibido: {text}\nTu JARVIS está en construcción."
        })

    return "OK"

@app.route("/", methods=["GET"])
def home():
    return "JARVIS BOT RUNNING"

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
