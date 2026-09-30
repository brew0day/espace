from flask import Flask, request
import requests
from datetime import datetime

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = "8986564824:AAGiYW3YLJphUiZUH4pGRUF3tkT2Tot2SVs"
TELEGRAM_CHAT_ID = "-5341829903"

@app.route('/pixel', methods=['GET'])
def tracker():
    """Reçoit le pixel tracker et envoie à Telegram"""

    # Récupérer les paramètres
    email = request.args.get('email', 'unknown')
    unique_id = request.args.get('id', 'unknown')

    # Récupérer l'IP publique du client (derrière un proxy)
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ',' in ip:
        ip = ip.split(',')[0].strip()

    # Récupérer le User-Agent (client mail : Gmail, Outlook, etc.)
    user_agent = request.headers.get('User-Agent', 'unknown')

    # Formater le message pour Telegram
    message = f"""📧 MAIL OUVERT

👤 Email: {email}
🌐 IP: {ip}
🔖 ID: {unique_id}
⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🔍 Client: {user_agent}"""

    # Envoyer à Telegram
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        })
    except:
        pass

    # Retourner un pixel vide (1x1 PNG transparent)
    return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0dIDAT\x08\xd9c\xf8\x0f\x00\x00\x01\x01\x00\x05\xb6\xee6\x81\x00\x00\x00\x00IEND\xaeB`\x82', 200, {'Content-Type': 'image/png'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
