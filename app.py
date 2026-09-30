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
    """Calcule le temps entre envoi et ouverture (format smart)"""
    try:
        sent_time = datetime.fromisoformat(sent_timestamp)
        open_time = datetime.now()
        total_seconds = int((open_time - sent_time).total_seconds())

        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            mins = total_seconds // 60
            secs = total_seconds % 60
            return f"{mins}m {secs}s"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            mins = (total_seconds % 3600) // 60
            return f"{hours}h {mins}m"
        else:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            return f"{days}d {hours}h"
    except:
        return 'N/A'

def detect_vpn_proxy(ip, headers):
    """Détecte un VPN/Proxy probable"""
    vpn_keywords = ['proxy', 'vpn', 'tor', 'i2p']
    headers_str = str(headers).lower()

    if any(keyword in headers_str for keyword in vpn_keywords):
        return "🚨 PROBABLE"

    if 'x-forwarded-for' in headers and headers.get('x-forwarded-for') != headers.get('x-real-ip', ''):
        return "⚠️ POSSIBLE"

    return "❌ Non détecté"

def get_all_headers(request):
    """Récupère tous les headers HTTP"""
    return {
        'DNT': request.headers.get('DNT', 'N/A'),
        'Accept-Encoding': request.headers.get('Accept-Encoding', 'N/A'),
        'Accept': request.headers.get('Accept', 'N/A'),
        'Sec-Fetch-Dest': request.headers.get('Sec-Fetch-Dest', 'N/A'),
        'Sec-Fetch-Mode': request.headers.get('Sec-Fetch-Mode', 'N/A'),
        'Sec-Fetch-Site': request.headers.get('Sec-Fetch-Site', 'N/A'),
        'Sec-Fetch-User': request.headers.get('Sec-Fetch-User', 'N/A'),
        'Upgrade-Insecure-Requests': request.headers.get('Upgrade-Insecure-Requests', 'N/A'),
    }

@app.route('/pixel', methods=['GET'])
def tracker():
    """Pixel tracker ULTRA avancé"""

    email = request.args.get('email', 'unknown')
    unique_id = request.args.get('id', 'unknown')
    sent_time = request.args.get('sent_time', 'N/A')
    js_data = request.args.get('js', '')

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
    vpn_status = detect_vpn_proxy(ip, request.headers)
    extra_headers = get_all_headers(request)

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    city_display = f"{geo['city']}" + (f", {geo['region']}" if geo['region'] else "")
    if city_display == "" or city_display == ", ":
        city_display = "Unknown"

    os_ver = ua_parsed['os'].version_string if hasattr(ua_parsed['os'], 'version_string') else str(ua_parsed['os'])
    device_fam = ua_parsed['device'].family if hasattr(ua_parsed['device'], 'family') else str(ua_parsed['device'])
    browser_fam = ua_parsed['browser'].family if hasattr(ua_parsed['browser'], 'family') else str(ua_parsed['browser'])
    browser_ver = ua_parsed['browser'].version_string if hasattr(ua_parsed['browser'], 'version_string') else ''

    js_section = ""
    if request.args.get('canvas'):
        js_section = f"""

🎨 CANVAS FINGERPRINT
   Canvas FP: {request.args.get('canvas', 'N/A')}
   Fonts: {request.args.get('fonts', 'N/A')}
   Audio FP: {request.args.get('audio', 'N/A')}

⏱️ PERFORMANCE
   Load Time: {request.args.get('perf', 'N/A')}
   Doc Size: {request.args.get('docsize', 'N/A')}
   Battery: {request.args.get('battery', 'N/A')}"""

    message = f"""🎯 MAIL INTERCEPTÉ 📬
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
👤 Email: {email}
🌐 IP: {ip}
🛡️ VPN/Proxy: {vpn_status}

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
🔒 DNT: {extra_headers['DNT']}
📦 Compression: {extra_headers['Accept-Encoding']}
🔐 Sec-Fetch: {extra_headers['Sec-Fetch-Dest']}

✅ Ouvert: {now}
⏳ Délai: {open_duration} après envoi
🔖 ID: {unique_id}{js_section}
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

@app.route('/tracker.svg', methods=['GET'])
def tracker_svg():
    """SVG tracker avec JavaScript pour fingerprinting avancé"""
    email = request.args.get('email', 'unknown')
    unique_id = request.args.get('id', 'unknown')

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1">
<script type="text/javascript">
(function() {{
    try {{
        var screen_res = window.screen.width + 'x' + window.screen.height;
        var dpi = window.devicePixelRatio || 1;
        var color = window.screen.colorDepth || 'N/A';
        var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
        var lang = navigator.language || navigator.userLanguage;
        var platform = navigator.platform || 'N/A';
        var cores = navigator.hardwareConcurrency || 'N/A';
        var ram = navigator.deviceMemory || 'N/A';

        var webgl = 'N/A';
        try {{
            var canvas2 = document.createElement('canvas');
            var gl = canvas2.getContext('webgl') || canvas2.getContext('experimental-webgl');
            if(gl) webgl = gl.getParameter(gl.VENDOR);
        }} catch(e) {{}}

        var plugins = navigator.plugins.length;
        var cookies = document.cookie ? document.cookie.split(';').length : 0;
        var wasm = typeof WebAssembly === 'undefined' ? 'NO' : 'YES';
        var sw = 'serviceWorker' in navigator ? 'YES' : 'NO';
        var storage = 'localStorage' in window ? 'YES' : 'NO';
        var indexdb = !!window.indexedDB ? 'YES' : 'NO';
        var conn = navigator.connection ? (navigator.connection.effectiveType || 'N/A') : 'N/A';

        var canvas_fp = 'N/A';
        try {{
            var canvas = document.createElement('canvas');
            canvas.width = 200;
            canvas.height = 50;
            var ctx = canvas.getContext('2d');
            ctx.textBaseline = 'top';
            ctx.font = '14px Arial';
            ctx.fillStyle = '#f60';
            ctx.fillRect(125, 1, 62, 20);
            ctx.fillStyle = '#069';
            ctx.fillText('Canvas FP', 2, 15);
            canvas_fp = canvas.toDataURL().substring(0, 50);
        }} catch(e) {{}}

        var fonts_list = 'N/A';
        try {{
            var baseFonts = ['monospace', 'sans-serif', 'serif'];
            var testFonts = ['Arial', 'Courier', 'Times', 'Verdana', 'Georgia', 'Palatino', 'Garamond', 'Bookman', 'Comic Sans MS', 'Trebuchet MS', 'Impact'];
            var canvas_f = document.createElement('canvas');
            canvas_f.width = 200;
            canvas_f.height = 50;
            var ctx_f = canvas_f.getContext('2d');
            var installed = [];
            testFonts.forEach(function(font) {{
                ctx_f.font = '20px ' + font + ', monospace';
                var w1 = ctx_f.measureText('mmmmmmmmmmlli').width;
                ctx_f.font = '20px monospace';
                var w2 = ctx_f.measureText('mmmmmmmmmmlli').width;
                if(w1 != w2) installed.push(font);
            }});
            fonts_list = installed.join(',') || 'Default';
        }} catch(e) {{}}

        var audio_fp = 'N/A';
        try {{
            var audioContext = new (window.AudioContext || window.webkitAudioContext)();
            var oscillator = audioContext.createOscillator();
            var analyser = audioContext.createAnalyser();
            oscillator.connect(analyser);
            analyser.connect(audioContext.destination);
            oscillator.start(0);
            var freqData = new Uint8Array(analyser.frequencyBinCount);
            analyser.getByteFrequencyData(freqData);
            audio_fp = freqData[0] + '-' + freqData[100] + '-' + freqData[200];
            oscillator.stop();
        }} catch(e) {{}}

        var perf_timing = 'N/A';
        try {{
            if(window.performance && window.performance.timing) {{
                var perfData = window.performance.timing;
                var pageLoadTime = perfData.loadEventEnd - perfData.navigationStart;
                perf_timing = pageLoadTime + 'ms';
            }}
        }} catch(e) {{}}

        var battery_status = 'N/A';
        try {{
            if(navigator.getBattery) {{
                navigator.getBattery().then(function(battery) {{
                    battery_status = battery.level * 100 + '% (' + (battery.charging ? 'Charging' : 'Discharging') + ')';
                }});
            }} else if(navigator.battery) {{
                battery_status = navigator.battery.level * 100 + '% (' + (navigator.battery.charging ? 'Charging' : 'Discharging') + ')';
            }}
        }} catch(e) {{}}

        var doc_props = 'N/A';
        try {{
            var docWidth = document.documentElement.scrollWidth || document.body.scrollWidth;
            var docHeight = document.documentElement.scrollHeight || document.body.scrollHeight;
            doc_props = docWidth + 'x' + docHeight;
        }} catch(e) {{}}

        var pixelUrl = '/pixel?email={email}&id={unique_id}&js=1&canvas=' + encodeURIComponent(canvas_fp) + '&fonts=' + encodeURIComponent(fonts_list) + '&audio=' + encodeURIComponent(audio_fp) + '&perf=' + encodeURIComponent(perf_timing) + '&battery=' + encodeURIComponent(battery_status) + '&docsize=' + encodeURIComponent(doc_props);

        var img = new Image();
        img.src = pixelUrl;
    }} catch(e) {{}}
}})();
</script>
</svg>"""
    return svg, 200, {'Content-Type': 'image/svg+xml'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
