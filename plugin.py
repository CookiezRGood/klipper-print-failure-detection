import logging
import threading
import time
import cv2
import numpy as np
import requests
import json
import os
from flask import Flask, jsonify, request, Response, send_from_directory

# Import TFLite Runtime
try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    logging.warning("CRITICAL: tflite-runtime not found. AI will not work.")
    tflite = None

# --- LOGGING ---
log = logging.getLogger('werkzeug')
log.disabled = True
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logging.info(">>> STARTING PLUGIN: RGB FIX + SMART LABELS <<<")

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.tflite')

# --- CLASS NAMES (Customize these to match your model) ---
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
        
        logging.info(f"TFLite Model Loaded. Input Shape: {input_shape}")
        return True
    except Exception as e:
        logging.error(f"Failed to load TFLite: {e}")
        return False

ai_ready = load_model()

def post_process_yolo(output_data, img_width, img_height, conf_threshold):
    # YOLOv8 Output is [1, 4+Nc, 8400]. Transpose to [8400, 4+Nc]
    output = np.transpose(output_data[0])
    
    boxes = []
    confidences = []
    class_ids = []
    
    x_factor = img_width / input_width
    y_factor = img_height / input_height

    # Slice scores (skip first 4 coords)
    scores = output[:, 4:]
    max_scores = np.max(scores, axis=1)
    max_indices = np.argmax(scores, axis=1)
    
    valid_indices = np.where(max_scores >= conf_threshold)[0]
    
    for i in valid_indices:
        score = max_scores[i]
        class_id = max_indices[i]
        row = output[i]
        
        cx, cy, w, h = row[0], row[1], row[2], row[3]
        
        left = int((cx - w/2) * x_factor)
        top = int((cy - h/2) * y_factor)
        width = int(w * x_factor)
        height = int(h * y_factor)
        
        # Clamp to image boundaries
        left = max(0, left)
        top = max(0, top)
        
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
        
        # 1. Resize
        resized = cv2.resize(image, (input_width, input_height))
        
        # 2. Convert BGR to RGB (Fixes color accuracy)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        
        # 3. Normalize
        input_data = np.expand_dims(rgb, axis=0)
        
        if input_details[0]['dtype'] == np.float32:
            input_data = (input_data.astype(np.float32) / 255.0)
        
        # 4. Run
        interpreter.set_tensor(input_details[0]['index'], input_data)
        interpreter.invoke()
        
        output_data = interpreter.get_tensor(output_details[0]['index'])
        
        user_conf = float(config.get("ai_threshold", 0.5))
        detections = post_process_yolo(output_data, original_w, original_h, user_conf)
        
        if not detections:
            return 0.0, []
            
        top_score = max(d['conf'] for d in detections)
        return top_score, detections
        
    except Exception as e:
        logging.error(f"Inference Error: {e}")
        return 0.0, []

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

            # --- TFLITE INFERENCE ---
            state["status"] = "monitoring"
            
            if ai_ready:
                score, detections = run_inference(state["latest_frame"])
                state["failure_score"] = score
                
                # Draw Boxes & Labels
                debug_img = state["latest_frame"].copy()
                detected_names = []
                
                for d in detections:
                    x, y, w, h = d['box']
                    cls_id = d['class']
                    
                    label = "Failure"
                    if cls_id < len(CLASS_NAMES):
                        label = CLASS_NAMES[cls_id]
                    detected_names.append(label)
                    
                    # Box Color: Red
                    cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 0, 255), 2)
                    
                    # Smart Label Positioning
                    text = f"{label} {int(d['conf']*100)}%"
                    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                    
                    # If box is at the very top, draw text INSIDE the box
                    if y < 20:
                        text_y = y + th + 5
                    else:
                        text_y = y - 5 # Standard (above box)

                    # Text Background
                    cv2.rectangle(debug_img, (x, text_y - th - 2), (x + tw, text_y + 2), (0, 0, 255), -1)
                    cv2.putText(debug_img, text, (x, text_y), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                
                state["annotated_frame"] = debug_img
                
                max_retries = int(config["consecutive_failures"])
                
                if score > float(config["ai_threshold"]):
                    if state["failure_count"] < max_retries:
                        state["failure_count"] += 1
                    
                    primary_cause = detected_names[0] if detected_names else "Failure"
                    
                    # Log the coordinates for debugging
                    logging.info(f"ALERT: Found {primary_cause} ({score:.2f}) | Count: {state['failure_count']}/{max_retries}")
                    
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
