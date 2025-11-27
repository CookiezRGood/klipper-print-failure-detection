import logging
import threading
import time
import cv2
import numpy as np
import requests
import json
import os
from flask import Flask, jsonify, request, Response, send_from_directory

# --- LOGGING ---
log = logging.getLogger('werkzeug')
log.disabled = True
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logging.info(">>> STARTING PLUGIN: COORDINATE DIAGNOSTIC MODE <<<")

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    logging.warning("CRITICAL: tflite-runtime not found.")
    tflite = None

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.tflite')

CLASS_NAMES = ["Spaghetti", "Stringing", "Zits"]

default_config = {
    "camera_url": "http://127.0.0.1/webcam/?action=snapshot",
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 500,
    "ai_threshold": 0.50,
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
    "annotated_frame": None,
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
input_height = 640
input_width = 640

def load_model():
    global interpreter, input_details, output_details, input_height, input_width
    if not os.path.exists(MODEL_PATH):
        logging.error(f"CRITICAL: model.tflite NOT FOUND at {MODEL_PATH}")
        return False
    
    try:
        interpreter = tflite.Interpreter(model_path=MODEL_PATH)
        interpreter.allocate_tensors()
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()
        input_shape = input_details[0]['shape']
        input_height = input_shape[1]
        input_width = input_shape[2]
        
        # LOGGING MODEL INFO
        logging.info(f"DIAGNOSTIC: Model Input Shape: {input_shape}")
        logging.info(f"DIAGNOSTIC: Output Details: {output_details[0]['shape']}")
        
        return True
    except Exception as e:
        logging.error(f"Failed to load TFLite: {e}")
        return False

ai_ready = load_model()

def post_process_yolo(output_data, img_width, img_height, conf_threshold):
    # Detect if we need transpose
    # YOLO output is usually [1, 4+Nc, 8400]
    if output_data.shape[1] < output_data.shape[2]:
        output = np.transpose(output_data[0])
    else:
        output = output_data[0]

    boxes = []
    confidences = []
    class_ids = []

    # DIAGNOSTIC: Check the raw values of the first row to guess format
    first_row = output[0]
    # Only log once to avoid spamming (we'll check logs)
    if not hasattr(post_process_yolo, "has_logged"):
        logging.info(f"DIAGNOSTIC: Raw Output Row [0]: {first_row[:6]}")
        post_process_yolo.has_logged = True

    # Check if normalized (values < 1.0)
    is_normalized = np.max(output[:, :4]) <= 1.0
    if is_normalized and not hasattr(post_process_yolo, "norm_logged"):
        logging.info("DIAGNOSTIC: Detected NORMALIZED coordinates (0.0-1.0)")
        post_process_yolo.norm_logged = True

    x_factor = img_width / input_width
    y_factor = img_height / input_height
    
    # If normalized, we scale by the *input* size first to get pixels
    if is_normalized:
        x_factor = img_width 
        y_factor = img_height 

    scores = output[:, 4:]
    max_scores = np.max(scores, axis=1)
    max_indices = np.argmax(scores, axis=1)
    
    valid_indices = np.where(max_scores >= conf_threshold)[0]
    
    for i in valid_indices:
        score = max_scores[i]
        class_id = max_indices[i]
        row = output[i]
        
        # YOLO Standard: cx, cy, w, h
        cx, cy, w, h = row[0], row[1], row[2], row[3]
        
        left = int((cx - w/2) * x_factor)
        top = int((cy - h/2) * y_factor)
        width = int(w * x_factor)
        height = int(h * y_factor)
        
        boxes.append([left, top, width, height])
        confidences.append(float(score))
        class_ids.append(int(class_id))

    indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, 0.45)
    
    final_results = []
    if len(indices) > 0:
        for i in indices.flatten():
            final_results.append({
                "box": boxes[i],
                "conf": confidences[i],
                "class": class_ids[i]
            })
            
    return final_results

def run_inference(image):
    if not ai_ready or interpreter is None: return 0.0, []
    
    try:
        original_h, original_w = image.shape[:2]
        resized = cv2.resize(image, (input_width, input_height))
        input_data = np.expand_dims(resized, axis=0)
        
        if input_details[0]['dtype'] == np.float32:
            input_data = (input_data.astype(np.float32) / 255.0)
        
        interpreter.set_tensor(input_details[0]['index'], input_data)
        interpreter.invoke()
        output_data = interpreter.get_tensor(output_details[0]['index'])
        
        user_conf = float(config.get("ai_threshold", 0.5))
        detections = post_process_yolo(output_data, original_w, original_h, user_conf)
        
        if not detections: return 0.0, []
        top_score = max(d['conf'] for d in detections)
        return top_score, detections
        
    except Exception as e:
        logging.error(f"Inference Error: {e}")
        return 0.0, []

# --- ROUTES (Same as before) ---
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

def trigger_printer_action(reason="Failure"):
    if state["action_triggered"]: return 
    action = config.get("on_failure", "nothing")
    url = config.get("moonraker_url", "http://127.0.0.1:7125").rstrip('/')
    logging.info(f"FAILURE CONFIRMED: {reason}. Action: {action}")
    try:
        console_msg = f"M118 >>> AI DETECTED {reason.upper()}! Action: {action.upper()} <<<"
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

            state["status"] = "monitoring"
            
            if ai_ready:
                score, detections = run_inference(state["latest_frame"])
                state["failure_score"] = score
                
                debug_img = state["latest_frame"].copy()
                detected_names = []
                
                for d in detections:
                    x, y, w, h = d['box']
                    cls_id = d['class']
                    label = "Failure"
                    if cls_id < len(CLASS_NAMES): label = CLASS_NAMES[cls_id]
                    detected_names.append(label)
                    
                    cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 0, 255), 2)
                    text = f"{label} {int(d['conf']*100)}%"
                    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                    cv2.rectangle(debug_img, (x, y-15), (x+tw, y), (0, 0, 255), -1)
                    cv2.putText(debug_img, text, (x, y-3), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                
                state["annotated_frame"] = debug_img
                
                max_retries = int(config["consecutive_failures"])
                if score > float(config["ai_threshold"]):
                    if state["failure_count"] < max_retries: state["failure_count"] += 1
                    primary_cause = detected_names[0] if detected_names else "Failure"
                    if state["failure_count"] >= max_retries:
                        state["status"] = "failure_detected"
                        trigger_printer_action(reason=primary_cause)
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
    img = state["annotated_frame"] if state["annotated_frame"] is not None else np.zeros((360, 640, 3), np.uint8)
    _, buffer = cv2.imencode('.jpg', img)
    return Response(buffer.tobytes(), mimetype='image/jpeg')
@app.route('/api/debug_frame')
def debug_frame(): return latest_frame()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
