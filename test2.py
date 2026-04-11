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
    <html>
    <head>
        <title>AI Fish Dashboard</title>
        <style>
            body { background:#0f172a; color:white; text-align:center; font-family:Arial; }
            img { width:70%; border-radius:10px; box-shadow:0 0 20px cyan; }
            .card { background:#1e293b; padding:10px; margin:10px; border-radius:10px; }
        </style>
    </head>
    <body>

        <h1>🐟 AI Fish Monitoring</h1>

        <img src="/video">

        <div id="detections"></div>
        <div id="data"></div>

        <script>
        async function update(){
            let r = await fetch('/api/data');
            let d = await r.json();

            document.getElementById('detections').innerHTML =
                "Detected: " + (d.detections.join(", ") || "None");

            document.getElementById('data').innerHTML = `
                <div class="card">Distance: ${d.distance}</div>
                <div class="card">Water Temp: ${d.waterTemp}</div>
                <div class="card">Surface Temp: ${d.surfaceTemp}</div>
                <div class="card">Pressure: ${d.pressure}</div>
                <div class="card">Altitude: ${d.altitude}</div>
                <div class="card">Turbidity: ${d.turbidity} (${d.quality})</div>
            `;
        }

        setInterval(update, 1000);
        update();
        </script>

    </body>
    </html>
    """)


# ================= RUN =================
if __name__ == "__main__":
    print("🚀 Open http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)  