import logging
import threading
import time
import cv2
import numpy as np
import requests
import json
import os
from flask import Flask, jsonify, request, Response, send_from_directory

# ================================================================
#   LOGGING SETUP (ADDED FOR FLOATING LOG PANEL)
# ================================================================

log = logging.getLogger("werkzeug")
log.disabled = True

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s"
)

logging.info(">>> STARTING PLUGIN <<<")

# Rolling log buffer
LOG_BUFFER = []
LOG_MAX_LINES = 300

def add_log(msg: str):
    """Store logs in a rolling buffer for the UI."""
    global LOG_BUFFER
    line = f"{time.strftime('%H:%M:%S')} - {msg}"
    LOG_BUFFER.append(line)
    if len(LOG_BUFFER) > LOG_MAX_LINES:
        LOG_BUFFER = LOG_BUFFER[-LOG_MAX_LINES:]
    print(line)  # Also print to console

# Patch logging.info / error so all logs also go to UI buffer
_old_info = logging.info
_old_error = logging.error
_old_warning = logging.warning

def patched_info(msg, *a, **k):
    add_log(msg)
    _old_info(msg, *a, **k)

def patched_error(msg, *a, **k):
    add_log("ERROR: " + msg)
    _old_error(msg, *a, **k)

def patched_warning(msg, *a, **k):
    add_log("WARNING: " + msg)
    _old_warning(msg, *a, **k)

logging.info = patched_info
logging.error = patched_error
logging.warning = patched_warning

# ================================================================
#   APP + SETTINGS
# ================================================================

app = Flask(__name__, static_folder="web_interface")

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "user_settings.json")
MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.tflite")

CLASS_NAMES = ["Spaghetti", "Stringing", "Zits"]

default_config = {
    "cameras": [
        {"id": 0, "name": "Primary", "url": "http://127.0.0.1/webcam/?action=snapshot", "enabled": True},
        {"id": 1, "name": "Secondary", "url": "", "enabled": False},
    ],
    "camera_count": 2,
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 500,
    "warn_threshold": 0.30,
    "ai_threshold": 0.50,
    "consecutive_failures": 2,
    "on_failure": "pause",
    "aspect_ratio": "16:9",

    # Mask zones
    "masks": {"0": [], "1": []},

    # Auto enable monitoring
    "auto_enable": False
}

config = default_config.copy()

if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r") as f:
            loaded = json.load(f)
            config.update(loaded)
            if "masks" not in config:
                config["masks"] = default_config["masks"]
            if "auto_enable" not in config:
                config["auto_enable"] = False
    except Exception:
        pass

def save_config_to_file():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception:
        pass

# ================================================================
#   RUNTIME STATE
# ================================================================

state = {
    "status": "idle",
    "failure_count": 0,
    "action_triggered": False,
    "monitoring_active": False,
    "auto_enabled": False,
    "user_disabled": False,
    "show_mask_overlay": False,
    "cameras": {
        0: {"frame": None, "score": 0.0},
        1: {"frame": None, "score": 0.0},
    },
}

# ================================================================
#   MODEL LOADING
# ================================================================

try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    logging.warning("tflite-runtime not found.")
    tflite = None

interpreter = None
input_details = None
output_details = None
input_height = 640
input_width = 640
input_dtype = np.float32

def load_model():
    global interpreter, input_details, output_details
    global input_height, input_width, input_dtype

    if not os.path.exists(MODEL_PATH):
        logging.error(f"model.tflite not found at {MODEL_PATH}")
        return False

    try:
        interpreter = tflite.Interpreter(model_path=MODEL_PATH)
        interpreter.allocate_tensors()

        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()

        shape = input_details[0]["shape"]
        input_height, input_width = shape[1], shape[2]
        input_dtype = input_details[0]["dtype"]

        logging.info(f"Loaded TFLite model, input={shape}")
        return True

    except Exception as e:
        logging.error(f"Failed to load TFLite: {e}")
        return False

ai_ready = load_model()

# ================================================================
#   AI INFERENCE
# ================================================================

def post_process_yolo(output_data, img_w, img_h, conf_threshold):
    if output_data.shape[1] < output_data.shape[2]:
        output = np.transpose(output_data[0])
    else:
        output = output_data[0]

    boxes = []
    confidences = []
    class_ids = []

    sample_coords = output[:, :4].flatten()
    is_norm = np.max(sample_coords) <= 1.5

    if is_norm:
        x_factor, y_factor = img_w, img_h
    else:
        x_factor = img_w / input_width
        y_factor = img_h / input_height

    scores = output[:, 4:]
    max_scores = np.max(scores, axis=1)
    max_indices = np.argmax(scores, axis=1)
    valid = np.where(max_scores >= conf_threshold)[0]

    for i in valid:
        sc = float(max_scores[i])
        cid = int(max_indices[i])
        cx, cy, w, h = output[i][:4]

        left = int((cx - w / 2) * x_factor)
        top = int((cy - h / 2) * y_factor)
        width = int(w * x_factor)
        height = int(h * y_factor)

        left = max(0, left)
        top = max(0, top)
        width = min(width, img_w - left)
        height = min(height, img_h - top)

        boxes.append([left, top, width, height])
        confidences.append(sc)
        class_ids.append(cid)

    indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, 0.45)

    results = []
    if len(indices) > 0:
        for i in indices.flatten():
            results.append({
                "box": boxes[i],
                "conf": confidences[i],
                "class": class_ids[i]
            })

    return results


def run_inference(image):
    if not ai_ready or interpreter is None:
        return 0.0, []

    try:
        orig_h, orig_w = image.shape[:2]
        resized = cv2.resize(image, (input_width, input_height))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        inp = np.expand_dims(rgb, 0)

        if input_dtype == np.float32:
            inp = inp.astype(np.float32) / 255.0
        elif input_dtype == np.uint8:
            inp = inp.astype(np.uint8)

        interpreter.set_tensor(input_details[0]["index"], inp)
        interpreter.invoke()

        out = interpreter.get_tensor(output_details[0]["index"])

        conf_thresh = float(config.get("warn_threshold", 0.3))
        detections = post_process_yolo(out, orig_w, orig_h, conf_thresh)

        if not detections:
            return 0.0, []

        best = max(d["conf"] for d in detections)
        return best, detections

    except Exception as e:
        logging.error(f"Inference failed: {e}")
        return 0.0, []

# ================================================================
#   HTTP ROUTES - CONTROL
# ================================================================

@app.route("/api/action/start", methods=["POST", "GET"])
def action_start():
    state["monitoring_active"] = True
    state["failure_count"] = 0
    state["auto_enabled"] = False
    state["user_disabled"] = False
    logging.info("Monitoring STARTED")
    return jsonify({"success": True})

@app.route("/api/action/stop", methods=["POST", "GET"])
def action_stop():
    state["monitoring_active"] = False
    state["user_disabled"] = True
    logging.info("Monitoring STOPPED (manual)")
    return jsonify({"success": True})


@app.route("/api/action/toggle_mask", methods=["POST"])
def toggle_mask():
    state["show_mask_overlay"] = request.json.get("show", False)
    return jsonify({"success": True})

# ================================================================
#   PRINT STATE (Moonraker)
# ================================================================

def get_printer_state():
    url = config.get("moonraker_url", "").rstrip("/")
    try:
        r = requests.get(f"{url}/printer/objects/query?print_stats", timeout=0.4)
        if r.status_code == 200:
            return r.json()["result"]["status"]["print_stats"]["state"]
    except:
        pass
    return "standby"

# ================================================================
#   ACTIONS ON FAILURE
# ================================================================

def trigger_printer_action(reason="Failure"):
    if state["action_triggered"]:
        return

    action = config.get("on_failure", "nothing")
    url = config.get("moonraker_url", "").rstrip("/")

    logging.info(f"Failure confirmed: {reason} | Action = {action}")

    try:
        requests.post(
            f"{url}/printer/gcode/script",
            json={"script": f"M118 >>> {reason.upper()}! Action: {action.upper()} <<<"}
        )

        if action == "pause":
            requests.post(f"{url}/printer/print/pause")
        elif action == "cancel":
            requests.post(f"{url}/printer/print/cancel")

    except Exception:
        pass

    state["action_triggered"] = True


# ================================================================
#   BACKGROUND MONITOR LOOP
# ================================================================

def background_monitor():
    logging.info("Monitor thread started.")

    while True:
        try:
            klip_state = get_printer_state()
            # Clear user-disabled flag at start of a NEW print
            if klip_state == "printing" and state.get("_last_state") != "printing":
                state["user_disabled"] = False

            # AUTO-ENABLE logic
            if config.get("auto_enable", False):

                # Auto-enable only if user did NOT manually stop monitoring
                if (
                    klip_state == "printing"
                    and not state["monitoring_active"]
                    and not state["user_disabled"]
                ):
                    logging.info("Auto-Enable: Print detected → Monitoring ON")
                    state["monitoring_active"] = True
                    state["auto_enabled"] = True

                # Auto-disable at end of print (only if it was auto-enabled)
                if (
                    klip_state in ["complete", "cancelled", "standby"]
                    and state["auto_enabled"]
                ):
                    logging.info("Auto-Enable: Print ended → Monitoring OFF")
                    state["monitoring_active"] = False
                    state["auto_enabled"] = False
                    state["user_disabled"] = False    # reset user disable for next print

            should_run = (
                state["monitoring_active"] or
                klip_state in ["printing", "paused"]
            )

            masks_cfg = config.get("masks", {})
            max_frame_score = 0.0

            cam_limit = int(config.get("camera_count", 2))

            for cam in config["cameras"]:
                cam_id = cam["id"]
                if cam_id >= cam_limit:
                    state["cameras"][cam_id]["score"] = 0.0
                    continue

                if not cam["enabled"] or not cam["url"]:
                    state["cameras"][cam_id]["score"] = 0.0
                    continue

                try:
                    r = requests.get(cam["url"], timeout=1.5)
                    if r.status_code != 200:
                        continue

                    arr = np.frombuffer(r.content, np.uint8)
                    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

                    # If decoding failed, skip this frame safely
                    if img is None:
                        logging.warning(f"Camera {cam_id} provided invalid image data.")
                        state["cameras"][cam_id]["score"] = 0.0
                        continue

                    debug = img.copy()
                    h, w = img.shape[:2]

                    # Apply masks
                    zones = masks_cfg.get(str(cam_id), [])
                    for z in zones:
                        try:
                            zx = float(z["x"])
                            zy = float(z["y"])
                            zw = float(z["w"])
                            zh = float(z["h"])
                        except:
                            continue

                        mx = int(zx * w)
                        my = int(zy * h)
                        mw = int(zw * w)
                        mh = int(zh * h)

                        mx = max(0, min(mx, w - 1))
                        my = max(0, min(my, h - 1))
                        mw = max(1, min(mw, w - mx))
                        mh = max(1, min(mh, h - my))

                        cv2.rectangle(img, (mx, my), (mx+mw, my+mh), (0,0,0), -1)

                        if state["show_mask_overlay"]:
                            overlay = debug.copy()
                            cv2.rectangle(
                                overlay,
                                (mx, my),
                                (mx+mw, my+mh),
                                (255, 0, 255),
                                -1
                            )
                            cv2.addWeighted(overlay, 0.20, debug, 0.80, 0, debug)

                    if not should_run:
                        state["cameras"][cam_id]["frame"] = debug
                        continue

                    # Run AI
                    score, dets = run_inference(img)
                    state["cameras"][cam_id]["score"] = score

                    if score > max_frame_score:
                        max_frame_score = score

                    # Draw detections
                    thresh = config.get("ai_threshold", 0.5)

                    for d in dets:
                        x, y, ww, hh = d["box"]
                        conf = d["conf"]
                        cid = d["class"]

                        label = CLASS_NAMES[cid] if cid < len(CLASS_NAMES) else "FAIL"

                        color = (0,0,255) if conf >= thresh else (0,255,255)
                        text_color = (255,255,255) if conf >= thresh else (0,0,0)

                        cv2.rectangle(debug, (x,y), (x+ww,y+hh), color, 2)

                        text = f"{label} {int(conf*100)}%"
                        (tw,th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)

                        ty = y - 5 if y > 20 else y + th + 5
                        cv2.rectangle(debug, (x, ty-th-2), (x+tw, ty+2), color, -1)
                        cv2.putText(debug, text, (x, ty),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 1)

                    state["cameras"][cam_id]["frame"] = debug

                except Exception as e:
                    logging.error(f"Camera {cam_id} error: {e}")

            # Status machine
            if not should_run:
                state["status"] = "idle"
                state["failure_count"] = 0
                state["action_triggered"] = False
                time.sleep(1)
                continue

            state["status"] = "monitoring"
            retries = int(config["consecutive_failures"])
            fail_thresh = float(config.get("ai_threshold", 0.5))

            if max_frame_score > fail_thresh:
                if state["failure_count"] < retries:
                    state["failure_count"] += 1

                logging.info(
                    f"Potential failure: {max_frame_score:.2f} "
                    f"(retry {state['failure_count']}/{retries})"
                )

                if state["failure_count"] >= retries:
                    state["status"] = "failure_detected"
                    trigger_printer_action("AI detection")
            else:
                if state["failure_count"] > 0:
                    state["failure_count"] -= 1

        except Exception as e:
            logging.error(f"Loop error: {e}")

        state["_last_state"] = klip_state

        time.sleep(float(config["check_interval"]) / 1000.0)

# Start thread
threading.Thread(target=background_monitor, daemon=True).start()

# ================================================================
#   STATIC FILES
# ================================================================

@app.route("/")
def serve_index():
    return send_from_directory("web_interface", "index.html")

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory("web_interface", path)

# ================================================================
#   SETTINGS API
# ================================================================

@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        incoming = request.json

        # Ensure new auto_enable key exists
        if "auto_enable" not in incoming:
            incoming["auto_enable"] = config.get("auto_enable", False)

        config.update(incoming)
        save_config_to_file()
        return jsonify({"status": "saved", "config": config})

    return jsonify(config)

# ================================================================
#   STATUS API
# ================================================================

@app.route("/api/status")
def get_status():
    max_score = max(
        state["cameras"][0]["score"],
        state["cameras"][1]["score"],
    )
    return jsonify({
        "status": state["status"],
        "score": max_score,
        "failures": state["failure_count"],
        "max_retries": config["consecutive_failures"]
    })

# ================================================================
#   FRAME API
# ================================================================

@app.route("/api/frame/<int:cam_id>")
def get_frame(cam_id):
    if cam_id not in state["cameras"] or state["cameras"][cam_id]["frame"] is None:
        blank = np.zeros((360, 640, 3), np.uint8)
        cv2.putText(blank, "NO SIGNAL / DISABLED", (50, 180),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (100,100,100), 2)
        ok, buf = cv2.imencode(".jpg", blank)
        return Response(buf.tobytes(), mimetype="image/jpeg")

    ok, buf = cv2.imencode(".jpg", state["cameras"][cam_id]["frame"])
    return Response(buf.tobytes(), mimetype="image/jpeg")

# ================================================================
#   LOG PANEL ENDPOINT (ADDED)
# ================================================================

@app.route("/api/logs")
def api_logs():
    """Return the last X lines of logs to the UI."""
    return jsonify({"logs": "\n".join(LOG_BUFFER)})

# ================================================================
#   RUN SERVER
# ================================================================

if __name__ == "__main__":
    add_log("Web server running at port 7126")
    app.run(host="0.0.0.0", port=7126, threaded=True)
