import logging
import threading
import time
import cv2
import numpy as np
import requests
import json
import os
from flask import Flask, jsonify, request, send_from_directory, Response

# Load TFLite
try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    logging.warning("CRITICAL: TFLite not found. Run install.sh again.")
    tflite = None

# --- LOGGING SETUP ---
# 1. Mute the web server spam
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# 2. Setup main logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logging.info(">>> STARTING PLUGIN: DEBUG MODE <<<")

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.tflite')

default_config = {
    "camera_url": "http://127.0.0.1/webcam/?action=snapshot",
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 2000,
    "ai_threshold": 0.60,
    "consecutive_failures": 2,
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
    "status": "idle",
    "failure_score": 0.0,
    "failure_count": 0,
    "action_triggered": False,
    "monitoring_active": False 
}

# --- AI ENGINE ---
interpreter = None
input_details = None
output_details = None

def load_model():
    global interpreter, input_details, output_details
    
    if not os.path.exists(MODEL_PATH):
        logging.error(f"CRITICAL: model.tflite NOT FOUND at {MODEL_PATH}")
        return False
    
    file_size = os.path.getsize(MODEL_PATH)
    logging.info(f"Found model.tflite (Size: {file_size} bytes)")
    
    try:
        interpreter = tflite.Interpreter(model_path=MODEL_PATH)
        interpreter.allocate_tensors()
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()
        logging.info("AI Model Loaded Successfully.")
        logging.info(f"Model Input Shape: {input_details[0]['shape']}")
        return True
    except Exception as e:
        logging.error(f"CRITICAL: Failed to load AI model: {e}")
        return False

ai_ready = load_model()

def run_inference(image):
    if not ai_ready or interpreter is None: return 0.0
    
    try:
        input_shape = input_details[0]['shape']
        height, width = input_shape[1], input_shape[2]
        
        resized = cv2.resize(image, (width, height))
        # Convert BGR to RGB (Critical for accuracy)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        
        input_data = np.expand_dims(rgb, axis=0)

        if input_details[0]['dtype'] == np.float32:
            input_data = np.float32(input_data) / 255.0

        interpreter.set_tensor(input_details[0]['index'], input_data)
        interpreter.invoke()

        output_data = interpreter.get_tensor(output_details[0]['index'])
        
        # Index 1 is typically the "Failure" class in standard spaghetti models
        raw_score = output_data[0][1]
        
        if output_details[0]['dtype'] == np.uint8:
            fail_score = float(raw_score) / 255.0
        else:
            fail_score = float(raw_score)
            
        return fail_score
        
    except Exception as e:
        logging.error(f"Inference Error: {e}")
        return 0.0

# --- ROUTES ---
@app.route('/api/action/start', methods=['POST', 'GET'])
def action_start():
    state["monitoring_active"] = True
    state["failure_count"] = 0
    logging.info("Manual Start Triggered")
    return jsonify({"success": True})

@app.route('/api/action/stop', methods=['POST', 'GET'])
def action_stop():
    state["monitoring_active"] = False
    logging.info("Manual Stop Triggered")
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
        console_msg = f"M118 >>> AI DETECTED FAILURE! Action: {action.upper()} <<<"
        requests.post(f"{url}/printer/gcode/script", json={"script": console_msg})
        if action == "pause": requests.post(f"{url}/printer/print/pause")
        elif action == "cancel": requests.post(f"{url}/printer/print/cancel")
        state["action_triggered"] = True
    except Exception: pass

def background_monitor():
    logging.info("Background monitor loop started.")
    
    while True:
        try:
            klipper_state = get_printer_state()
            if klipper_state in ["complete", "error", "cancelled"]:
                state["monitoring_active"] = False

            should_run = (klipper_state in ["printing", "paused"]) or state["monitoring_active"]

            # Always fetch image for UI
            resp = requests.get(config['camera_url'], timeout=2)
            if resp.status_code == 200:
                arr = np.frombuffer(resp.content, np.uint8)
                img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                state["latest_frame"] = img
            else:
                logging.error("Camera connection failed.")
                state["status"] = "connection_error"
                time.sleep(2)
                continue

            if not should_run:
                state["status"] = "idle"
                state["failure_count"] = 0
                state["action_triggered"] = False
                time.sleep(1)
                continue

            state["status"] = "monitoring"
            
            # Run AI
            score = run_inference(state["latest_frame"])
            state["failure_score"] = score
            
            # --- DEBUG LOGGING (Visible in journalctl) ---
            logging.info(f"DEBUG: AI Score: {score:.4f} | Threshold: {config.get('ai_threshold')}")

            threshold = float(config.get("ai_threshold", 0.6))

            if score > threshold:
                state["failure_count"] += 1
                logging.info(f"ALERT: Failure detected ({state['failure_count']}/{int(config['consecutive_failures'])})")
                
                if state["failure_count"] >= int(config["consecutive_failures"]):
                    state["status"] = "failure_detected"
                    trigger_printer_action()
            else:
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
    img = state["latest_frame"] if state["latest_frame"] is not None else np.zeros((360, 640, 3), np.uint8)
    # Draw Debug Score directly on image
    debug_img = img.copy()
    color = (0, 255, 0) if state["failure_score"] < float(config["ai_threshold"]) else (0, 0, 255)
    cv2.putText(debug_img, f"AI: {int(state['failure_score']*100)}%", (20, 50), 
                cv2.FONT_HERSHEY_SIMPLEX, 1, color, 2)
    _, buffer = cv2.imencode('.jpg', debug_img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')
@app.route('/api/debug_frame')
def debug_frame(): return latest_frame()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
