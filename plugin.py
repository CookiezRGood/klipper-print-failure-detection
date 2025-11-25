import logging
import threading
import time
import cv2
import numpy as np
import requests
import json
import os
from flask import Flask, jsonify, request, Response, send_from_directory

# Import YOLO Engine
try:
    from ultralytics import YOLO
except ImportError:
    logging.warning("CRITICAL: Ultralytics not found. AI will not work.")
    YOLO = None

logging.basicConfig(level=logging.INFO)
logging.info(">>> STARTING PLUGIN: PERFORMANCE LOGGING <<<")

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.pt')

default_config = {
    "camera_url": "http://127.0.0.1/webcam/?action=snapshot",
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 2000,
    "ai_threshold": 0.50,
    "consecutive_failures": 1,
    "on_failure": "pause",
    "aspect_ratio": "16:9",
    "preview_refresh_rate": 500
}

config = default_config.copy()
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, 'r') as f:
            config.update(json.load(f))
    except Exception: pass

def save_config_to_file():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception: pass

state = {
    "latest_frame": None,
    "annotated_frame": None,
    "status": "idle",
    "failure_score": 0.0,
    "failure_count": 0,
    "action_triggered": False,
    "monitoring_active": False 
}

# --- AI ENGINE ---
model = None

def load_model():
    global model
    if not os.path.exists(MODEL_PATH):
        logging.error(f"CRITICAL: model.pt NOT FOUND at {MODEL_PATH}")
        return False
    
    try:
        logging.info("Loading YOLOv8 Model... (This may take 30s)")
        model = YOLO(MODEL_PATH, task='detect')
        logging.info("YOLOv8 Model Loaded Successfully.")
        return True
    except Exception as e:
        logging.error(f"Failed to load YOLO: {e}")
        return False

ai_ready = load_model()

# --- ROUTES ---
@app.route('/api/action/start', methods=['POST', 'GET'])
def action_start():
    state["monitoring_active"] = True
    state["failure_count"] = 0
    state["action_triggered"] = False
    logging.info("Monitoring STARTED")
    return jsonify({"success": True})

@app.route('/api/action/stop', methods=['POST', 'GET'])
def action_stop():
    state["monitoring_active"] = False
    logging.info("Monitoring STOPPED")
    return jsonify({"success": True})

def get_printer_state():
    url = config.get("moonraker_url", "http://127.0.0.1:7125").rstrip('/')
    try:
        r = requests.get(f"{url}/printer/objects/query?print_stats", timeout=0.5)
        if r.status_code == 200:
            data = r.json()
            return data.get("result", {}).get("status", {}).get("print_stats", {}).get("state", "standby")
    except Exception: pass
    return "standby"

def trigger_printer_action():
    if state["action_triggered"]: return 
    action = config.get("on_failure", "nothing")
    url = config.get("moonraker_url", "http://127.0.0.1:7125").rstrip('/')
    logging.info(f"FAILURE CONFIRMED. Action: {action}")
    try:
        console_msg = f"M118 >>> YOLO DETECTED FAILURE! Action: {action.upper()} <<<"
        requests.post(f"{url}/printer/gcode/script", json={"script": console_msg})
        if action == "pause": requests.post(f"{url}/printer/print/pause")
        elif action == "cancel": requests.post(f"{url}/printer/print/cancel")
        state["action_triggered"] = True
    except Exception: pass

def background_monitor():
    while True:
        try:
            klipper_state = get_printer_state()
            if klipper_state in ["complete", "error", "cancelled"]:
                state["monitoring_active"] = False

            should_run = (klipper_state in ["printing", "paused"]) or state["monitoring_active"]

            # Fetch Image
            resp = requests.get(config['camera_url'], timeout=2)
            if resp.status_code == 200:
                arr = np.frombuffer(resp.content, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                state["latest_frame"] = img
                if not should_run:
                    state["annotated_frame"] = img
            else:
                state["status"] = "connection_error"
                time.sleep(2)
                continue

            if not should_run:
                state["status"] = "idle"
                state["failure_count"] = 0
                state["action_triggered"] = False
                time.sleep(1)
                continue

            # --- AI INFERENCE ---
            state["status"] = "monitoring"
            
            if model:
                user_conf = float(config.get("ai_threshold", 0.5))
                
                # --- PERFORMANCE TIMER START ---
                start_time = time.time()
                
                results = model(state["latest_frame"], conf=user_conf, verbose=False)
                
                # --- PERFORMANCE TIMER END ---
                duration = time.time() - start_time
                
                # Log time only if it's slow (>1s) to avoid spamming too much
                if duration > 1.0:
                    logging.info(f"PERFORMANCE: Inference took {duration:.2f} seconds")
                
                result = results[0]
                state["annotated_frame"] = result.plot()
                
                box_count = len(result.boxes)
                max_retries = int(config["consecutive_failures"])
                
                if box_count > 0:
                    top_conf = float(result.boxes.conf[0])
                    state["failure_score"] = top_conf
                    
                    if state["failure_count"] < max_retries:
                        state["failure_count"] += 1
                    
                    logging.info(f"YOLO Alert: {box_count} objects. Conf: {top_conf:.2f} | Count: {state['failure_count']}/{max_retries}")
                    
                    if state["failure_count"] >= max_retries:
                        state["status"] = "failure_detected"
                        trigger_printer_action()
                else:
                    state["failure_score"] = 0.0
                    state["failure_count"] = 0

        except Exception as e:
            logging.error(f"Loop Error: {e}")
        
        time.sleep(float(config["check_interval"]) / 1000.0)

monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()

# Routes
@app.route('/')
def serve_index(): return send_from_directory('web_interface', 'index.html')
@app.route('/<path:path>')
def serve_static(path): return send_from_directory('web_interface', path)
@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        config.update(request.json)
        save_config_to_file()
        return jsonify({"status": "saved", "config": config})
    return jsonify(config)
@app.route('/api/status', methods=['GET'])
def get_status():
    return jsonify({
        "status": state["status"],
        "score": state["failure_score"],
        "failures": state["failure_count"],
        "max_retries": config["consecutive_failures"]
    })
@app.route('/api/latest_frame')
def latest_frame():
    img = state["annotated_frame"] if state["annotated_frame"] is not None else np.zeros((360, 640, 3), np.uint8)
    _, buffer = cv2.imencode('.jpg', img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')
@app.route('/api/debug_frame')
def debug_frame(): return latest_frame()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
