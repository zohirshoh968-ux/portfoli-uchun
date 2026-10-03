import os
import requests
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# Bot tokenni Vercel Environment Variables dan yoki to'g'ridan-to'g'ri oling
BOT_TOKEN = os.environ.get("BOT_TOKEN", "BOT_TOKENINI_SHUYERGA_YOZING")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# 1. Asosiy web-sahifa (index.html ni ko'rsatadi)
@app.route("/")
def home():
    return render_template("index.html")

# 2. Telegram Webhook qabul qiluvchi route
@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()

    if update and "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")

        # Javob matnini tayyorlash
        if text == "/start":
            reply_text = "Salom! Men Vercel-da ishlayotgan Telegram botman! 🚀"
        else:
            reply_text = f"Siz yozdingiz: {text}"

        # Telegramga xabar yuborish
        send_message(chat_id, reply_text)

    return jsonify({"status": "ok"}), 200

def send_message(chat_id, text):
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    requests.post(url, json=payload)

if __name__ == "__main__":
    app.run(debug=True)
