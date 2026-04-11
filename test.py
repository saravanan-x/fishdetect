from flask import Flask, render_template_string, Response, jsonify
import cv2
import requests
import json
import time
import numpy as np
from ultralytics import YOLO
import threading
import random  # For simulating temp/pressure/alt

app = Flask(__name__)

# Config
ESP_IP = '192.168.4.1'  # ESP32 AP IP
CAPTURE_URL = f'http://{ESP_IP}/capture'
DATA_URL = f'http://{ESP_IP}/data'
STREAM_URL = f'http://{ESP_IP}/stream'  # Not used directly; we poll capture for simplicity

# Globals for latest data
latest_frame = None
latest_distance = 0.0
latest_detections = []  # NEW: Store latest detection labels
sensor_data = {
    'temp': 25.0,  # Simulated; replace with real sensor
    'pres_hpa': 1013.25,  # Simulated
    'alt': 10.5,  # Simulated
    'sea_level_hpa': 1013.25  # Simulated
}
chart_data = {'labels': [], 'values': []}  # For JS chart

# Load custom YOLO model (your best.pt file - place it in the same directory as this script)
model = YOLO('seafish.pt')  # CHANGED: Use your custom model instead of yolov8n.pt

def fetch_and_process_frame():
    global latest_frame, latest_detections
    try:
        # Fetch JPEG from ESP32
        resp = requests.get(CAPTURE_URL, timeout=5)
        if resp.status_code == 200:
            nparr = np.frombuffer(resp.content, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            # Object detection with custom model
            if frame is not None:
                results = model(frame, verbose=False)
                annotated_frame = results[0].plot()  # Draw boxes/labels
                
                # NEW: Extract unique detection labels (class names)
                if results[0].boxes is not None:
                    cls_ids = results[0].boxes.cls.cpu().numpy()
                    labels = [model.names[int(cls_id)] for cls_id in set(cls_ids)]  # Unique labels
                    latest_detections = labels
                else:
                    latest_detections = []
                
                # Save/encode latest annotated frame
                _, buffer = cv2.imencode('.jpg', annotated_frame)
                latest_frame = buffer.tobytes()
    except Exception as e:
        print(f"Frame fetch error: {e}")
        latest_detections = []  # Reset on error

def fetch_sensor_data():
    global latest_distance, sensor_data
    try:
        resp = requests.get(DATA_URL, timeout=5)
        if resp.status_code == 200:
            data = json.loads(resp.text)
            latest_distance = data['value']
            
            # Simulate other sensors (replace with real ESP32 extensions)
            sensor_data['temp'] = random.uniform(24, 28)  # e.g., from DHT22
            sensor_data['pres_hpa'] = random.uniform(1010, 1020)  # e.g., from BMP280
            sensor_data['alt'] = random.uniform(5, 15)  # Derived from pressure
            sensor_data['sea_level_hpa'] = 1013.25
    except Exception as e:
        print(f"Sensor fetch error: {e}")

# Background threads for polling
def frame_poller():
    while True:
        fetch_and_process_frame()
        time.sleep(1)  # Poll every second

def sensor_poller():
    while True:
        fetch_sensor_data()
        # Update chart (keep last 20 points)
        now = time.strftime('%H:%M:%S')
        chart_data['labels'].append(now)
        chart_data['values'].append(latest_distance)
        if len(chart_data['labels']) > 20:
            chart_data['labels'].pop(0)
            chart_data['values'].pop(0)
        time.sleep(1)

# Start threads
threading.Thread(target=frame_poller, daemon=True).start()
threading.Thread(target=sensor_poller, daemon=True).start()

# HTML Template (adapted from original, with JS for polling)
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fish Monitor System</title>
<script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;500;700&display=swap');
body{
    margin:0;
    font-family:'Poppins',sans-serif;
    background:linear-gradient(135deg,#0f2027,#203a43,#2c5364);
    color:#fff;
    min-height:100vh;
    display:flex;
    align-items:center;
    justify-content:center
}
.container{
    background:rgba(255,255,255,0.1);
    backdrop-filter:blur(12px);
    border-radius:20px;
    padding:35px;
    box-shadow:0 10px 40px rgba(0,0,0,0.5);
    text-align:center;
    width:90%;
    max-width:900px
}
h1{
    font-size:2.4em;
    background:linear-gradient(90deg,#00dbde,#fc00ff);
    -webkit-background-clip:text;
    -webkit-text-fill-color:transparent;
}
img{
    width:80%;
    max-width:600px;
    margin:20px;
    border-radius:15px;
    border:4px solid #00ffea;
}
canvas{
    width:100%;
    max-width:700px;
    height:350px;
    margin:20px auto;
}
.readings{
    font-size:1.3em;
    margin-top:20px;
}
.value{
    font-weight:700;
    color:#00ffea;
}
.footer{
    margin-top:20px;
    font-size:0.9em;
    color:#88cccc;
}
#detections {
    margin:20px;
    font-size:1.1em;
    color:#00ffea;
    font-weight: bold;
}
</style>
</head>
<body>
<div class="container">
<h1>🐟 Fish Monitor System</h1>
<h2>Live Video with Custom AI Detection</h2>
<img id="video" src="/video" alt="Processed Video Stream">
<h2>HC-SR04 Distance Chart (cm)</h2>
<canvas id="chart"></canvas>
<div id="detections">Detected Labels: Loading...</div>
<script>
const ctx = document.getElementById('chart').getContext('2d');
const chart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: {{ chart_labels|tojson }},
        datasets: [{
            label: 'Water Level (cm)',
            borderColor: 'rgb(0,255,234)',
            backgroundColor: 'rgba(0,255,234,0.2)',
            data: {{ chart_values|tojson }},
            fill: true,
            tension: 0.3
        }]
    },
    options: {
        responsive: true,
        scales: {
            x: { title: { display: true, text: 'Time' } },
            y: { title: { display: true, text: 'Distance (cm)' } }
        }
    }
});

// Poll for latest frame
function updateVideo() {
    document.getElementById('video').src = '/video?' + new Date().getTime();
}
setInterval(updateVideo, 1000);

// Poll for sensor data and update chart/readings
function updateData() {
    fetch('/api/data')
    .then(response => response.json())
    .then(data => {
        // Update chart
        if(chart.data.labels.length > 20){
            chart.data.labels.shift();
            chart.data.datasets[0].data.shift();
        }
        chart.data.labels.push(new Date().toLocaleTimeString());
        chart.data.datasets[0].data.push(data.distance);
        chart.update();

        // Update readings
        document.querySelectorAll('.reading')[0].innerHTML = `🌡️ Temperature: <span class="value">${data.temp} °C</span>`;
        document.querySelectorAll('.reading')[1].innerHTML = `🗜️ Pressure: <span class="value">${data.pres_hpa} hPa</span>`;
        document.querySelectorAll('.reading')[2].innerHTML = `🗻 Altitude: <span class="value">${data.alt} m</span>`;
        
        // UPDATED: Display detection labels from custom model
        document.getElementById('detections').innerHTML = `Detected Labels: ${data.detections.join(', ') || 'None'}`;
    })
    .catch(err => console.error(err));
}
setInterval(updateData, 1000);
updateData();  // Initial load
</script>
<div class="readings">
<div class="reading">🌡️ Temperature: <span class="value">Loading...</span></div>
<div class="reading">🗜️ Pressure: <span class="value">Loading...</span></div>
<div class="reading">🗻 Altitude: <span class="value">Loading...</span></div>
</div>
<div class="footer">
Sea-level: {{ sea_level_hpa }} hPa <br>
ESP32 Fish + Weather Monitor (Python Dashboard with Custom AI)
</div>
</div>
</body>
</html>
'''

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, 
                                  chart_labels=chart_data['labels'], 
                                  chart_values=chart_data['values'],
                                  sea_level_hpa=sensor_data['sea_level_hpa'])

@app.route('/video')
def video_feed():
    if latest_frame is None:
        return '', 404
    return Response(latest_frame, mimetype='image/jpeg')

@app.route('/api/data')
def api_data():
    return jsonify({
        'distance': latest_distance,
        'temp': sensor_data['temp'],
        'pres_hpa': sensor_data['pres_hpa'],
        'alt': sensor_data['alt'],
        'detections': latest_detections  # UPDATED: Pass real detections from model
    })

if __name__ == '__main__':
    print("Starting Python Dashboard... Connect to ESP32 WiFi first!")
    print("Open http://localhost:5000 in browser.")
    app.run(host='0.0.0.0', port=5000, debug=True)