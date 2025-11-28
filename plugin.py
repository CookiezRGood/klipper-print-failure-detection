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
logging.info(">>> STARTING PLUGIN <<<")

# Import TFLite Runtime
try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    logging.warning("CRITICAL: tflite-runtime not found. AI will not work.")
    tflite = None

app = Flask(__name__, static_folder='web_interface')

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), 'user_settings.json')
MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model.tflite')

CLASS_NAMES = ["Spaghetti", "Stringing", "Zits"]

default_config = {
    "cameras": [
        {"id": 0, "name": "Primary", "url": "http://127.0.0.1/webcam/?action=snapshot", "enabled": True},
        {"id": 1, "name": "Secondary", "url": "", "enabled": False}
    ],
    "camera_count": 2,
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 500,
    "warn_threshold": 0.30,
    "ai_threshold": 0.50,
    "consecutive_failures": 2,
    "on_failure": "pause",
    "aspect_ratio": "16:9",

    # NEW: per-camera mask zones (normalized coordinates 0–1)
    # "masks": { "0": [ {x,y,w,h}, ... ], "1": [ ... ] }
    "masks": {
        "0": [],
        "1": []
    }
}

config = default_config.copy()
if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, 'r') as f:
            loaded = json.load(f)
            config.update(loaded)
            if "masks" not in config:
                config["masks"] = default_config["masks"]
    except Exception:
        pass


def save_config_to_file():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(config, f, indent=4)
    except Exception:
        pass


state = {
    "status": "idle",
    "failure_count": 0,
    "action_triggered": False,
    "monitoring_active": False,
    "show_mask_overlay": False,
    "cameras": {
        0: {"frame": None, "score": 0.0},
        1: {"frame": None, "score": 0.0}
    }
}


# --- AI ENGINE ---
interpreter = None
input_details = None
output_details = None
input_height = 640
input_width = 640
input_dtype = np.float32


def load_model():
    global interpreter, input_details, output_details, input_height, input_width, input_dtype
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
        input_dtype = input_details[0]['dtype']
        
        logging.info(f"TFLite Model Loaded. Shape: {input_shape}")
        return True
    except Exception as e:
        logging.error(f"Failed to load TFLite: {e}")
        return False


ai_ready = load_model()


def post_process_yolo(output_data, img_width, img_height, conf_threshold):
    if output_data.shape[1] < output_data.shape[2]:
        output = np.transpose(output_data[0])
    else:
        output = output_data[0]

    boxes = []
    confidences = []
    class_ids = []

    sample_coords = output[:, :4].flatten()
    is_normalized = np.max(sample_coords) <= 1.5
    
    if is_normalized:
        x_factor = img_width
        y_factor = img_height
    else:
        x_factor = img_width / input_width
        y_factor = img_height / input_height

    scores = output[:, 4:]
    max_scores = np.max(scores, axis=1)
    max_indices = np.argmax(scores, axis=1)

    valid_indices = np.where(max_scores >= conf_threshold)[0]

    for i in valid_indices:
        score = float(max_scores[i])
        class_id = int(max_indices[i])
        row = output[i]

        cx, cy, w, h = row[0], row[1], row[2], row[3]

        left = int((cx - w/2) * x_factor)
        top = int((cy - h/2) * y_factor)
        width = int(w * x_factor)
        height = int(h * y_factor)

        left = max(0, left)
        top = max(0, top)
        width = min(width, img_width - left)
        height = min(height, img_height - top)

        boxes.append([left, top, width, height])
        confidences.append(score)
        class_ids.append(class_id)

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
    if not ai_ready or interpreter is None:
        return 0.0, []
    
    try:
        original_h, original_w = image.shape[:2]
        resized = cv2.resize(image, (input_width, input_height))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        input_data = np.expand_dims(rgb, axis=0)

        if input_details[0]['dtype'] == np.float32:
            input_data = (input_data.astype(np.float32) / 255.0)
        elif input_details[0]['dtype'] == np.uint8:
            input_data = input_data.astype(np.uint8)

        interpreter.set_tensor(input_details[0]['index'], input_data)
        interpreter.invoke()

        output_data = interpreter.get_tensor(output_details[0]['index'])

        user_conf = float(config.get("warn_threshold", 0.3))
        detections = post_process_yolo(output_data, original_w, original_h, user_conf)

        if not detections:
            return 0.0, []

        top_score = max(d['conf'] for d in detections)
        return top_score, detections

    except Exception as e:
        logging.error(f"Inference Error: {e}")
        return 0.0, []


# --- ROUTES / CONTROL ---
@app.route('/api/action/start', methods=['POST', 'GET'])
def action_start():
    state["monitoring_active"] = True
    state["failure_count"] = 0
    logging.info("Monitoring STARTED")
    return jsonify({"success": True})


@app.route('/api/action/stop', methods=['POST', 'GET'])
def action_stop():
    state["monitoring_active"] = False
    logging.info("Monitoring STOPPED")
    return jsonify({"success": True})


@app.route('/api/action/toggle_mask', methods=['POST'])
def toggle_mask():
    data = request.json
    state["show_mask_overlay"] = data.get("show", False)
    return jsonify({"success": True})


def get_printer_state():
    url = config.get("moonraker_url", "http://127.0.0.1:7125").rstrip('/')
    try:
        r = requests.get(f"{url}/printer/objects/query?print_stats", timeout=0.5)
        if r.status_code == 200:
            data = r.json()
            return data.get("result", {}).get("status", {}).get("print_stats", {}).get("state", "standby")
    except Exception:
        pass
    return "standby"


def trigger_printer_action(reason="Failure"):
    if state["action_triggered"]:
        return
    action = config.get("on_failure", "nothing")
    url = config.get("moonraker_url", "http://127.0.0.1:7125").rstrip('/')
    logging.info(f"FAILURE CONFIRMED: {reason}. Action: {action}")
    try:
        console_msg = f"M118 >>> AI DETECTED {reason.upper()}! Action: {action.upper()} <<<"
        requests.post(f"{url}/printer/gcode/script", json={"script": console_msg})
        if action == "pause":
            requests.post(f"{url}/printer/print/pause")
        elif action == "cancel":
            requests.post(f"{url}/printer/print/cancel")
        state["action_triggered"] = True
    except Exception:
        pass


def background_monitor():
    while True:
        try:
            klipper_state = get_printer_state()
            if klipper_state in ["complete", "error", "cancelled"]:
                state["monitoring_active"] = False

            should_run = (klipper_state in ["printing", "paused"]) or state["monitoring_active"]

            max_frame_score = 0.0
            cam_limit = int(config.get("camera_count", 2))

            masks_cfg = config.get("masks", {})

            for cam in config["cameras"]:
                cam_id = cam["id"]
                if cam_id >= cam_limit:
                    state["cameras"][cam_id]["score"] = 0.0
                    continue
                if not cam["enabled"] or not cam["url"]:
                    state["cameras"][cam_id]["score"] = 0.0
                    continue

                try:
                    resp = requests.get(cam["url"], timeout=2)
                    if resp.status_code == 200:
                        arr = np.frombuffer(resp.content, np.uint8)
                        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

                        debug_img = img.copy()
                        h, w = img.shape[:2]

                        cam_key = str(cam_id)
                        zones = masks_cfg.get(cam_key, [])

                        # --- APPLY BLACK MASKS TO AI IMAGE ---
                        for z in zones:
                            try:
                                zx = float(z.get("x", 0.0))
                                zy = float(z.get("y", 0.0))
                                zw = float(z.get("w", 0.0))
                                zh = float(z.get("h", 0.0))
                            except Exception:
                                continue

                            if zw <= 0 or zh <= 0:
                                continue

                            mx = int(zx * w)
                            my = int(zy * h)
                            mw = int(zw * w)
                            mh = int(zh * h)

                            mx = max(0, min(mx, w-1))
                            my = max(0, min(my, h-1))
                            mw = max(1, min(mw, w - mx))
                            mh = max(1, min(mh, h - my))

                            cv2.rectangle(img, (mx, my), (mx + mw, my + mh), (0, 0, 0), -1)

                        # --- VISUAL OVERLAY ON DEBUG IMAGE (20% opacity) ---
                        if state["show_mask_overlay"] and zones:
                            overlay = debug_img.copy()
                            for z in zones:
                                try:
                                    zx = float(z.get("x", 0.0))
                                    zy = float(z.get("y", 0.0))
                                    zw = float(z.get("w", 0.0))
                                    zh = float(z.get("h", 0.0))
                                except Exception:
                                    continue

                                if zw <= 0 or zh <= 0:
                                    continue

                                mx = int(zx * w)
                                my = int(zy * h)
                                mw = int(zw * w)
                                mh = int(zh * h)

                                mx = max(0, min(mx, w-1))
                                my = max(0, min(my, h-1))
                                mw = max(1, min(mw, w - mx))
                                mh = max(1, min(mh, h - my))

                                cv2.rectangle(overlay, (mx, my), (mx + mw, my + mh), (255, 0, 255), -1)

                            alpha = 0.2  # 20% mask, 80% original
                            cv2.addWeighted(overlay, alpha, debug_img, 1.0 - alpha, 0, debug_img)

                        if not should_run:
                            state["cameras"][cam_id]["frame"] = debug_img
                            state["cameras"][cam_id]["score"] = 0.0
                            continue

                        if ai_ready:
                            score, detections = run_inference(img)
                            trigger_thresh = float(config.get("ai_threshold", 0.5))

                            for d in detections:
                                x, y, w_box, h_box = d['box']
                                cls_id = d['class']
                                conf = d['conf']
                                label = CLASS_NAMES[cls_id] if cls_id < len(CLASS_NAMES) else "Failure"

                                box_color = (0, 0, 255) if conf >= trigger_thresh else (0, 255, 255)
                                text_color = (255, 255, 255) if conf >= trigger_thresh else (0, 0, 0)

                                h_img, w_img = debug_img.shape[:2]
                                x = max(0, min(x, w_img))
                                y = max(0, min(y, h_img))
                                w_box = max(0, min(w_box, w_img - x))
                                h_box = max(0, min(h_box, h_img - y))

                                cv2.rectangle(debug_img, (x, y), (x + w_box, y + h_box), box_color, 2)

                                text = f"{label} {int(conf*100)}%"
                                (tw, th), _ = cv2.getTextSize(text,
                                                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                                text_y = y + th + 5 if y < 20 else y - 5
                                cv2.rectangle(debug_img,
                                              (x, text_y - th - 2),
                                              (x + tw, text_y + 2),
                                              box_color, -1)
                                cv2.putText(debug_img, text, (x, text_y),
                                            cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                            text_color, 1)

                            state["cameras"][cam_id]["frame"] = debug_img
                            state["cameras"][cam_id]["score"] = score
                            if score > max_frame_score:
                                max_frame_score = score

                except Exception:
                    pass

            # State handling
            if not should_run:
                state["status"] = "idle"
                state["failure_count"] = 0
                state["action_triggered"] = False
                time.sleep(1)
                continue

            state["status"] = "monitoring"
            max_retries = int(config["consecutive_failures"])
            threshold = float(config.get("ai_threshold", 0.5))

            if max_frame_score > threshold:
                if state["failure_count"] < max_retries:
                    state["failure_count"] += 1

                logging.info(f"ALERT: Failure {max_frame_score:.2f} | Count: {state['failure_count']}")

                if state["failure_count"] >= max_retries:
                    state["status"] = "failure_detected"
                    trigger_printer_action(reason="AI Detection")

            else:
                if state["failure_count"] > 0:
                    state["failure_count"] -= 1

        except Exception as e:
            logging.error(f"Loop Error: {e}")

        time.sleep(float(config["check_interval"]) / 1000.0)


monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()


@app.route('/')
def serve_index():
    return send_from_directory('web_interface', 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('web_interface', path)


@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        config.update(request.json)
        save_config_to_file()
        return jsonify({"status": "saved", "config": config})
    return jsonify(config)


@app.route('/api/status', methods=['GET'])
def get_status():
    max_score = max(state["cameras"][0]["score"], state["cameras"][1]["score"])
    return jsonify({
        "status": state["status"],
        "score": max_score,
        "failures": state["failure_count"],
        "max_retries": config["consecutive_failures"]
    })


@app.route('/api/frame/<int:cam_id>')
def get_frame(cam_id):
    if cam_id not in state["cameras"] or state["cameras"][cam_id]["frame"] is None:
        blank = np.zeros((360, 640, 3), np.uint8)
        cv2.putText(blank, "NO SIGNAL / DISABLED", (50, 180),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (100, 100, 100), 2)
        _, buffer = cv2.imencode('.jpg', blank)
        return Response(buffer.tobytes(), mimetype='image/jpeg')
    _, buffer = cv2.imencode('.jpg', state["cameras"][cam_id]["frame"])
    return Response(buffer.tobytes(), mimetype='image/jpeg')


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=7126, threaded=True)
