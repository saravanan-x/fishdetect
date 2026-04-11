from flask import Flask, render_template_string, Response, jsonify
import requests
import numpy as np
import cv2
import time
from ultralytics import YOLO
import threading

app = Flask(__name__)

# ================= CONFIG =================
ESP_IP = '192.168.1.13'
STREAM_URL = f'http://{ESP_IP}/stream'
DATA_URL = f'http://{ESP_IP}/sensors'

# Globals
latest_detections = []
sensor_data = {
    'distance': 0.0,
    'waterTemp': -99.0,
    'surfaceTemp': -99.0,
    'pressure': -1.0,
    'altitude': -1.0,
    'turbidity': 0,
    'quality': "Unknown"
}

# Load YOLO
model = YOLO('seafish.pt')

# ================= MJPEG STREAM (FIXED) =================
def generate_frames():
    global latest_detections

    while True:
        try:
            stream = requests.get(STREAM_URL, stream=True, timeout=10)
            bytes_data = b''

            for chunk in stream.iter_content(chunk_size=2048):
                if not chunk:
                    continue

                bytes_data += chunk

                a = bytes_data.find(b'\xff\xd8')
                b = bytes_data.find(b'\xff\xd9')

                if a != -1 and b != -1:
                    jpg = bytes_data[a:b+2]
                    bytes_data = bytes_data[b+2:]

                    frame = cv2.imdecode(np.frombuffer(jpg, dtype=np.uint8), cv2.IMREAD_COLOR)
                    if frame is None:
                        continue

                    results = model(frame, verbose=False)

                    labels = []
                    for r in results:
                        for box in r.boxes:
                            cls = int(box.cls[0])
                            label = model.names[cls]
                            labels.append(label)

                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                            cv2.rectangle(frame, (x1,y1), (x2,y2), (0,255,0), 2)
                            cv2.putText(frame, label, (x1, y1-10),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0), 2)

                    latest_detections = list(set(labels))

                    _, buffer = cv2.imencode('.jpg', frame)
                    frame = buffer.tobytes()

                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

        except Exception as e:
            print("Stream reconnecting...", e)
            time.sleep(2)


# ================= SENSOR FETCH =================
def sensor_poller():
    while True:
        try:
            r = requests.get(DATA_URL, timeout=5)
            if r.status_code == 200:
                data = r.json()
                sensor_data.update(data)
        except Exception as e:
            print("Sensor error:", e)

        time.sleep(3)   

# Start sensor thread
threading.Thread(target=sensor_poller, daemon=True).start()

# ================= ROUTES =================

@app.route('/video')
def video():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/data')
def data():
    return jsonify({
        **sensor_data,
        "detections": latest_detections
    })


@app.route('/')
def index():
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<title>AI Marine Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
    --ocean: #00e5ff;
    --ocean-dim: #006e7f;
    --deep: #020c1b;
    --surface: #071428;
    --card: #0a1f3a;
    --card2: #071830;
    --glow: rgba(0,229,255,0.12);
    --warn: #ff9f1c;
    --safe: #00f5a0;
    --text: #cce8f4;
    --muted: #4a7a96;
}

body {
    margin: 0;
    font-family: 'Share Tech Mono', monospace;
    background: var(--deep);
    color: var(--text);
    overflow: hidden;
}

/* Scanline overlay */
body::after {
    content: '';
    position: fixed;
    inset: 0;
    background: repeating-linear-gradient(
        0deg,
        transparent,
        transparent 2px,
        rgba(0,0,0,0.06) 2px,
        rgba(0,0,0,0.06) 4px
    );
    pointer-events: none;
    z-index: 999;
}

/* ─── LAYOUT ─── */
.container {
    display: grid;
    grid-template-columns: 1fr 380px;
    height: 100vh;
    gap: 0;
}

/* ─── HEADER BAR ─── */
.header-bar {
    grid-column: 1 / -1;
    background: var(--surface);
    border-bottom: 1px solid var(--ocean-dim);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 20px;
    height: 48px;
    flex-shrink: 0;
}

.header-bar .logo {
    font-family: 'Orbitron', monospace;
    font-size: 14px;
    font-weight: 900;
    color: var(--ocean);
    letter-spacing: 4px;
    text-transform: uppercase;
}

.header-bar .tagline {
    font-size: 11px;
    color: var(--muted);
    letter-spacing: 2px;
}

.header-bar .clock {
    font-size: 13px;
    color: var(--ocean);
    letter-spacing: 2px;
}

/* Make container 3-row: header + content split */
.main-wrap {
    display: flex;
    flex-direction: column;
    height: 100vh;
}

.content-row {
    display: grid;
    grid-template-columns: 1fr 380px;
    flex: 1;
    overflow: hidden;
}

/* ─── VIDEO ─── */
.video-section {
    padding: 16px;
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.video-label {
    font-family: 'Orbitron', monospace;
    font-size: 10px;
    letter-spacing: 3px;
    color: var(--ocean);
    text-transform: uppercase;
    display: flex;
    align-items: center;
    gap: 8px;
}

.video-label::before {
    content: '';
    display: inline-block;
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--safe);
    box-shadow: 0 0 8px var(--safe);
    animation: blink 1.4s ease-in-out infinite;
}

@keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.3; }
}

.video-wrapper {
    flex: 1;
    position: relative;
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid var(--ocean-dim);
    background: #000;
}

.video-wrapper img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
}

/* HUD corners */
.video-wrapper::before,
.video-wrapper::after,
.hud-corner-bl,
.hud-corner-br {
    content: '';
    position: absolute;
    width: 18px; height: 18px;
    z-index: 2;
}
.video-wrapper::before {
    top: 0; left: 0;
    border-top: 2px solid var(--ocean);
    border-left: 2px solid var(--ocean);
}
.video-wrapper::after {
    top: 0; right: 0;
    border-top: 2px solid var(--ocean);
    border-right: 2px solid var(--ocean);
}
.hud-corner-bl {
    bottom: 0; left: 0;
    border-bottom: 2px solid var(--ocean);
    border-left: 2px solid var(--ocean);
}
.hud-corner-br {
    bottom: 0; right: 0;
    border-bottom: 2px solid var(--ocean);
    border-right: 2px solid var(--ocean);
}

.video-overlay {
    position: absolute;
    top: 10px; left: 10px;
    font-size: 10px;
    color: var(--ocean);
    letter-spacing: 1px;
    opacity: 0.7;
    z-index: 2;
}

/* ─── PANEL ─── */
.panel {
    background: var(--surface);
    border-left: 1px solid var(--ocean-dim);
    display: flex;
    flex-direction: column;
    gap: 0;
    overflow-y: auto;
    padding: 14px 12px;
    scrollbar-width: thin;
    scrollbar-color: var(--ocean-dim) transparent;
}

.panel-title {
    font-family: 'Orbitron', monospace;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 4px;
    color: var(--ocean);
    text-align: center;
    padding-bottom: 12px;
    border-bottom: 1px solid rgba(0,229,255,0.15);
    margin-bottom: 12px;
    text-transform: uppercase;
}

/* ─── CARDS ─── */
.card {
    background: var(--card);
    border: 1px solid rgba(0,229,255,0.15);
    border-radius: 8px;
    padding: 12px 14px;
    margin-bottom: 10px;
    position: relative;
    overflow: hidden;
}

.card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 1px;
    background: linear-gradient(90deg, transparent, var(--ocean), transparent);
    opacity: 0.4;
}

.card-title {
    font-family: 'Orbitron', monospace;
    font-size: 9px;
    letter-spacing: 3px;
    color: var(--muted);
    text-transform: uppercase;
    margin-bottom: 10px;
}

/* ─── STATUS ROW ─── */
.status-row {
    display: flex;
    justify-content: space-around;
    align-items: center;
}

.status-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 5px;
    font-size: 10px;
    color: var(--muted);
    letter-spacing: 1px;
    text-transform: uppercase;
}

.dot-wrap {
    display: flex;
    align-items: center;
    gap: 5px;
}

.dot {
    height: 10px;
    width: 10px;
    border-radius: 50%;
    flex-shrink: 0;
}

.green {
    background: var(--safe);
    box-shadow: 0 0 8px var(--safe);
    animation: pulse-green 2s ease-in-out infinite;
}

.red {
    background: #ff3b3b;
    box-shadow: 0 0 8px #ff3b3b;
}

@keyframes pulse-green {
    0%, 100% { box-shadow: 0 0 6px var(--safe); }
    50% { box-shadow: 0 0 14px var(--safe); }
}

/* ─── RADAR ─── */
.radar-card { text-align: center; }

.radar-wrap {
    position: relative;
    width: 130px;
    height: 130px;
    margin: 0 auto 8px;
}

.radar-circle {
    width: 130px;
    height: 130px;
    border-radius: 50%;
    border: 1px solid rgba(0,229,255,0.4);
    position: relative;
    background:
        radial-gradient(circle, rgba(0,229,255,0.04) 0%, transparent 70%);
}

/* Inner rings */
.radar-circle::before,
.radar-circle::after {
    content: '';
    position: absolute;
    border-radius: 50%;
    border: 1px solid rgba(0,229,255,0.15);
    top: 50%; left: 50%;
    transform: translate(-50%,-50%);
}
.radar-circle::before { width: 65px; height: 65px; }
.radar-circle::after  { width: 32px; height: 32px; }

/* Crosshairs */
.crossh, .crossv {
    position: absolute;
    background: rgba(0,229,255,0.12);
}
.crossh { width: 100%; height: 1px; top: 50%; left: 0; }
.crossv { width: 1px; height: 100%; left: 50%; top: 0; }

.sweep {
    position: absolute;
    width: 50%;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--ocean));
    top: 50%;
    left: 50%;
    transform-origin: left center;
    animation: sweep 2.5s linear infinite;
    border-radius: 0 1px 1px 0;
}

/* Sweep gradient trail */
.sweep-trail {
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: conic-gradient(
        rgba(0,229,255,0.0) 0deg,
        rgba(0,229,255,0.08) 45deg,
        rgba(0,229,255,0.0) 90deg,
        transparent 90deg
    );
    animation: trail-spin 2.5s linear infinite;
}

@keyframes sweep {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
}
@keyframes trail-spin {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
}

/* Radar blip */
.blip {
    position: absolute;
    width: 5px; height: 5px;
    border-radius: 50%;
    background: var(--ocean);
    box-shadow: 0 0 6px var(--ocean);
    animation: blip-fade 2.5s ease-out infinite;
}

@keyframes blip-fade {
    0%   { opacity: 0; }
    30%  { opacity: 1; }
    100% { opacity: 0; }
}

.radar-label {
    font-family: 'Orbitron', monospace;
    font-size: 8px;
    letter-spacing: 3px;
    color: var(--muted);
    text-transform: uppercase;
}

/* ─── DETECTIONS ─── */
.badge-wrap {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 4px;
}

.badge {
    display: inline-block;
    background: rgba(0,229,255,0.1);
    color: var(--ocean);
    border: 1px solid rgba(0,229,255,0.35);
    padding: 4px 10px;
    border-radius: 4px;
    font-size: 11px;
    letter-spacing: 1px;
    text-transform: uppercase;
}

.no-detect {
    font-size: 11px;
    color: var(--muted);
    letter-spacing: 1px;
}

/* ─── SENSOR DATA ─── */
.data-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px 8px;
}

.data-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
}

.data-label {
    font-size: 9px;
    color: var(--muted);
    letter-spacing: 1.5px;
    text-transform: uppercase;
}

.data-value {
    font-family: 'Orbitron', monospace;
    font-size: 14px;
    font-weight: 700;
    color: var(--ocean);
}

.data-unit {
    font-size: 9px;
    color: var(--muted);
    margin-left: 2px;
    font-family: 'Share Tech Mono', monospace;
    font-weight: 400;
}

.quality-pill {
    display: inline-block;
    font-size: 9px;
    padding: 1px 6px;
    border-radius: 3px;
    letter-spacing: 1px;
    text-transform: uppercase;
    margin-left: 4px;
}

/* ─── TELEMETRY ─── */
.telem-grid {
    display: grid;
    gap: 6px;
}

.telem-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid rgba(0,229,255,0.07);
    padding-bottom: 6px;
}

.telem-row:last-child { border-bottom: none; padding-bottom: 0; }

.telem-key {
    font-size: 9px;
    letter-spacing: 1.5px;
    color: var(--muted);
    text-transform: uppercase;
}

.telem-val {
    font-family: 'Orbitron', monospace;
    font-size: 13px;
    color: var(--text);
    font-weight: 700;
}

.telem-val.warn { color: var(--warn); }
.telem-val.safe { color: var(--safe); }

/* ─── STATUS BAR ─── */
.status-bar {
    background: var(--card2);
    border: 1px solid rgba(0,229,255,0.12);
    border-radius: 6px;
    padding: 8px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 10px;
}

/* ─── SCROLLBAR ─── */
.panel::-webkit-scrollbar { width: 3px; }
.panel::-webkit-scrollbar-track { background: transparent; }
.panel::-webkit-scrollbar-thumb { background: var(--ocean-dim); border-radius: 2px; }
</style>
</head>

<body>
<div class="main-wrap">

    <!-- HEADER -->
    <div class="header-bar">
        <div class="logo">&#9651; MarineAI</div>
        <div class="tagline">VESSEL INTELLIGENCE SYSTEM &nbsp;/&nbsp; DEEP SEA OPERATIONS</div>
        <div class="clock" id="clock">--:--:--</div>
    </div>

    <div class="content-row">

        <!-- VIDEO FEED -->
        <div class="video-section">
            <div class="video-label">Live Feed &mdash; CAM-01</div>
            <div class="video-wrapper">
                <div class="hud-corner-bl"></div>
                <div class="hud-corner-br"></div>
                <div class="video-overlay">REC &bull; 1080p &bull; 30fps</div>
                <img src="/video" alt="Live Feed">
            </div>
        </div>

        <!-- PANEL -->
        <div class="panel">
            <div class="panel-title">&#9651; Ship AI System</div>

            <!-- STATUS LIGHTS -->
            <div class="card">
                <div class="card-title">System Status</div>
                <div class="status-row">
                    <div class="status-item">
                        <div class="dot-wrap">
                            <span id="camStatus" class="dot green"></span>
                            <span>Camera</span>
                        </div>
                        <span style="font-size:9px;color:var(--safe)" id="camText">ONLINE</span>
                    </div>
                    <div style="width:1px; height:32px; background:rgba(0,229,255,0.15)"></div>
                    <div class="status-item">
                        <div class="dot-wrap">
                            <span id="sensorStatus" class="dot green"></span>
                            <span>Sensors</span>
                        </div>
                        <span style="font-size:9px;color:var(--safe)" id="sensorText">ONLINE</span>
                    </div>
                </div>
            </div>

            <!-- RADAR -->
            <div class="card radar-card">
                <div class="card-title">Detection Radar</div>
                <div class="radar-wrap">
                    <div class="radar-circle">
                        <div class="crossh"></div>
                        <div class="crossv"></div>
                        <div class="sweep-trail"></div>
                        <div class="sweep"></div>
                        <!-- Blips -->
                        <div class="blip" style="top:28%;left:62%;animation-delay:0.8s"></div>
                        <div class="blip" style="top:58%;left:34%;animation-delay:1.9s"></div>
                        <div class="blip" style="top:72%;left:70%;animation-delay:0.3s"></div>
                    </div>
                </div>
                <div class="radar-label">Active Scan &bull; 360&deg;</div>
            </div>

            <!-- DETECTIONS -->
            <div class="card">
                <div class="card-title">Detected Objects</div>
                <div class="badge-wrap" id="detections">
                    <span class="no-detect">Scanning&hellip;</span>
                </div>
            </div>

            <!-- SENSOR DATA -->
            <div class="card">
                <div class="card-title">Sensor Data</div>
                <div class="data-grid" id="data">
                    <div class="data-item"><div class="data-label">Distance</div><div class="data-value">--<span class="data-unit">m</span></div></div>
                    <div class="data-item"><div class="data-label">Water Temp</div><div class="data-value">--<span class="data-unit">&deg;C</span></div></div>
                    <div class="data-item"><div class="data-label">Surface Temp</div><div class="data-value">--<span class="data-unit">&deg;C</span></div></div>
                    <div class="data-item"><div class="data-label">Pressure</div><div class="data-value">--<span class="data-unit">Pa</span></div></div>
                    <div class="data-item"><div class="data-label">Altitude</div><div class="data-value">--<span class="data-unit">m</span></div></div>
                    <div class="data-item"><div class="data-label">Turbidity</div><div class="data-value">--</div></div>
                </div>
            </div>

            <!-- TELEMETRY -->
            <div class="card">
                <div class="card-title">Ship Telemetry</div>
                <div class="telem-grid" id="extra">
                    <div class="telem-row"><span class="telem-key">Speed</span><span class="telem-val" id="t-speed">--</span></div>
                    <div class="telem-row"><span class="telem-key">Heading</span><span class="telem-val" id="t-heading">--</span></div>
                    <div class="telem-row"><span class="telem-key">Battery</span><span class="telem-val" id="t-battery">--</span></div>
                    <div class="telem-row"><span class="telem-key">Status</span><span class="telem-val" id="t-status">--</span></div>
                </div>
            </div>

        </div><!-- /panel -->
    </div><!-- /content-row -->
</div><!-- /main-wrap -->

<script>
// Clock
function tickClock(){
    document.getElementById('clock').textContent =
        new Date().toLocaleTimeString('en-GB',{hour12:false});
}
setInterval(tickClock,1000); tickClock();

async function update(){
    try {
        let r = await fetch('/api/data');
        let d = await r.json();

        // DETECTIONS
        let detHTML = "";
        d.detections.forEach(obj=>{
            detHTML += `<span class="badge">${obj}</span>`;
        });
        document.getElementById('detections').innerHTML =
            detHTML || '<span class="no-detect">No objects detected</span>';

        // SENSOR DATA
        let qColor = d.quality === 'Good' ? 'var(--safe)' : 'var(--warn)';
        document.getElementById('data').innerHTML = `
            <div class="data-item">
                <div class="data-label">Distance</div>
                <div class="data-value">${d.distance}<span class="data-unit">m</span></div>
            </div>
            <div class="data-item">
                <div class="data-label">Water Temp</div>
                <div class="data-value">${d.waterTemp}<span class="data-unit">&deg;C</span></div>
            </div>
            <div class="data-item">
                <div class="data-label">Surface Temp</div>
                <div class="data-value">${d.surfaceTemp}<span class="data-unit">&deg;C</span></div>
            </div>
            <div class="data-item">
                <div class="data-label">Pressure</div>
                <div class="data-value">${d.pressure}<span class="data-unit">Pa</span></div>
            </div>
            <div class="data-item">
                <div class="data-label">Altitude</div>
                <div class="data-value">${d.altitude}<span class="data-unit">m</span></div>
            </div>
            <div class="data-item">
                <div class="data-label">Turbidity</div>
                <div class="data-value">${d.turbidity}
                    <span class="quality-pill" style="background:${qColor}22;color:${qColor};border:1px solid ${qColor}44">${d.quality}</span>
                </div>
            </div>
        `;

        // TELEMETRY
        let speed   = (Math.random()*20).toFixed(2);
        let heading = (Math.random()*360).toFixed(0);
        let battery = (50 + Math.random()*50).toFixed(0);
        let stable  = battery > 60;

        document.getElementById('t-speed').textContent   = speed + ' kn';
        document.getElementById('t-heading').textContent = heading + '\u00b0';
        document.getElementById('t-battery').textContent = battery + '%';
        let statusEl = document.getElementById('t-status');
        statusEl.textContent = stable ? 'STABLE' : 'WARNING';
        statusEl.className = 'telem-val ' + (stable ? 'safe' : 'warn');

        // STATUS LIGHTS
        let camOk = d.detections && d.detections.length >= 0;
        let senOk = d.distance != 0;

        document.getElementById('camStatus').className = 'dot ' + (camOk ? 'green' : 'red');
        document.getElementById('camText').textContent = camOk ? 'ONLINE' : 'OFFLINE';
        document.getElementById('camText').style.color = camOk ? 'var(--safe)' : '#ff3b3b';

        document.getElementById('sensorStatus').className = 'dot ' + (senOk ? 'green' : 'red');
        document.getElementById('sensorText').textContent = senOk ? 'ONLINE' : 'OFFLINE';
        document.getElementById('sensorText').style.color = senOk ? 'var(--safe)' : '#ff3b3b';

    } catch(e) {
        document.getElementById('sensorStatus').className = 'dot red';
        document.getElementById('sensorText').textContent = 'ERROR';
        document.getElementById('sensorText').style.color = '#ff3b3b';
    }
}

setInterval(update, 1500);
update();
</script>

</body>
</html>
""")

# ================= RUN =================
if __name__ == "__main__":
    print("🚀 Open http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)  