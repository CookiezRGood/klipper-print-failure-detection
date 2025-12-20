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

ENABLE_TIMING_LOGS = False   # set False to disable all timing logs

app = Flask(__name__, static_folder="web_interface")

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "user_settings.json")
MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.tflite")

CLASS_NAMES = ["Spaghetti", "Blob", "Warping", "Crack"]

CATEGORY_KEYS = [name.lower() for name in CLASS_NAMES]

def stats_block():
    """Create a stats dict for one camera, including per-category counters."""
    return {
        "detections": 0,
        "failures": 0,
        "per_category": {
            key: {"detections": 0, "failures": 0}
            for key in CATEGORY_KEYS
        },
    }

def normalize_per_category(stats):
    """
    Ensure all current CATEGORY_KEYS exist in per_category stats.
    Allows safe migration when model classes change.
    """
    per_cat = stats.get("per_category", {})
    for key in CATEGORY_KEYS:
        if key not in per_cat:
            per_cat[key] = {"detections": 0, "failures": 0}
    stats["per_category"] = per_cat

default_config = {
    "cameras": [
        {"id": 0, "name": "Primary", "url": "http://127.0.0.1/webcam/?action=snapshot", "enabled": True},
        {"id": 1, "name": "Secondary", "url": "", "enabled": False},
    ],
    "camera_count": 1,
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 500,
    "consecutive_failures": 3,
    "on_failure": "pause",
    "infer_every_n_loops": 1,
    "cam1_aspect_ratio": "4:3",
    "cam2_aspect_ratio": "4:3",
    "notify_mobileraker": False,

    # Mask zones
    "masks": {"0": [], "1": []},

    # Per-category AI settings (spaghetti, stringing, zits)
    "ai_categories": {
        "spaghetti": {
            "enabled": True,
            "trigger": True,
            "detect_threshold": 0.30,
            "trigger_threshold": 0.70
        },
        "blob": {
            "enabled": True,
            "trigger": False,
            "detect_threshold": 0.30,
            "trigger_threshold": 0.70
        },
        "warping": {
            "enabled": True,
            "trigger": False,
            "detect_threshold": 0.30,
            "trigger_threshold": 0.70
        },
        "crack": {
            "enabled": True,
            "trigger": False,
            "detect_threshold": 0.30,
            "trigger_threshold": 0.70
        },
    },
}

config = default_config.copy()

if os.path.exists(SETTINGS_FILE):
    try:
        with open(SETTINGS_FILE, "r") as f:
            loaded = json.load(f)
            config.update(loaded)
            if "notify_mobileraker" not in config:
                config["notify_mobileraker"] = False
            if "masks" not in config:
                config["masks"] = default_config["masks"]
            if "ai_categories" not in config:
                config["ai_categories"] = default_config["ai_categories"]
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
    "failure_cam": None,
    "failure_reason": None,
    "action_triggered": False,
    "monitoring_active": False,
    "manual_override": False,
    "show_mask_overlay": False,
    "cameras": {
        0: {"frame": None, "score": 0.0},
        1: {"frame": None, "score": 0.0},
    },
    "stats": {
        0: stats_block(),
        1: stats_block()
    },
}

# Cache last inference results per camera
last_inference = {
    0: {"score": 0.0, "dets": []},
    1: {"score": 0.0, "dets": []},
}

FAILURE_HISTORY = []
MAX_FAILURE_HISTORY = 30

# Normalize stats categories (handles model upgrades)
for cam_id in state["stats"]:
    normalize_per_category(state["stats"][cam_id])

# ================================================================
#   CAMERA READY SETUP
# ================================================================

CAM_SESSIONS = {
    0: requests.Session(),
    1: requests.Session(),
}
MOONRAKER_SESSION = requests.Session()

camera_ready = {0: False, 1: False}

def wait_for_camera(cam_id, url, timeout_seconds=8):
    """Wait until a camera responds with HTTP 200 or timeout expires."""
    start = time.time()

    while time.time() - start < timeout_seconds:
        try:
            r = CAM_SESSIONS.get(cam_id, requests).get(url, timeout=1.2)
            if r.status_code == 200:
                logging.info(f"Camera {cam_id} is ready.")
                camera_ready[cam_id] = True
                return True
        except Exception:
            pass

        time.sleep(0.6)

    logging.warning(f"Camera {cam_id} did NOT become ready before timeout.")
    camera_ready[cam_id] = False
    return False

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
        interpreter = tflite.Interpreter(
            model_path=MODEL_PATH,
            num_threads=2
        )
            
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

        cats = config.get("ai_categories", {})
        detect_thresholds = [
            c.get("detect_threshold", 0.3)
            for c in cats.values()
            if c.get("enabled", True)
        ]

        conf_thresh = min(detect_thresholds) if detect_thresholds else 0.3
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
    FAILURE_HISTORY.clear()
    state["stats"][0] = stats_block()
    state["stats"][1] = stats_block()
    normalize_per_category(state["stats"][0])
    normalize_per_category(state["stats"][1])
    state["monitoring_active"] = True
    state["failure_count"] = 0
    state["action_triggered"] = False
    state["failure_cam"] = None
    state["failure_reason"] = None
    state["manual_override"] = True
    logging.info("Monitoring STARTED (manual)")
    return jsonify({"success": True})

@app.route("/api/action/stop", methods=["POST", "GET"])
def action_stop():
    state["monitoring_active"] = False
    state["failure_cam"] = None
    state["failure_reason"] = None
    logging.info("Monitoring STOPPED")
    return jsonify({"success": True})

@app.route("/api/action/start_from_macro", methods=["POST"])
def action_start_from_macro():
    FAILURE_HISTORY.clear()
    state["stats"][0] = stats_block()
    state["stats"][1] = stats_block()
    normalize_per_category(state["stats"][0])
    normalize_per_category(state["stats"][1])
    state["monitoring_active"] = True
    state["failure_count"] = 0
    state["action_triggered"] = False
    state["failure_cam"] = None
    state["failure_reason"] = None
    state["manual_override"] = False
    logging.info("Monitoring STARTED (print start macro)")
    return jsonify({"success": True})

@app.route("/api/action/toggle_mask", methods=["POST"])
def toggle_mask():
    state["show_mask_overlay"] = request.json.get("show", False)
    return jsonify({"success": True})

@app.route("/api/stats/reset/<int:cam_id>", methods=["POST"])
def reset_camera_stats(cam_id):
    if cam_id not in state["stats"]:
        return jsonify({"success": False, "error": "Invalid camera"}), 400

    state["stats"][cam_id] = stats_block()

    logging.info(f"Stats reset for camera {cam_id}")
    return jsonify({"success": True})

# ================================================================
#   PRINT STATE (Moonraker)
# ================================================================

def get_printer_state():
    url = config.get("moonraker_url", "").rstrip("/")
    try:
        r = MOONRAKER_SESSION.get(f"{url}/printer/objects/query?print_stats", timeout=0.4)
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
        
        # --- Mobileraker notification (optional) ---
        if config.get("notify_mobileraker", False):
            action_name = {
                "nothing": "Warning",
                "pause": "Pause Print",
                "cancel": "Cancel Print"
            }.get(action, action)

            notify_msg = f"⚠️ AI Failure Detected – Action: {action_name}"

            requests.post(
                f"{url}/printer/gcode/script",
                json={"script": f'MR_NOTIFY MESSAGE="{notify_msg}"'}
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
        loop_start = time.perf_counter()
        state["_infer_tick"] = state.get("_infer_tick", 0) + 1
        infer_every = max(1, int(config.get("infer_every_n_loops", 1)))
        do_infer = (state["_infer_tick"] % infer_every == 0)
        
        if ENABLE_TIMING_LOGS:
            t_state = t_cameras = t_infer = t_draw = 0.0
        try:
            if ENABLE_TIMING_LOGS:
                t0 = time.perf_counter()

            klip_state = get_printer_state()

            if ENABLE_TIMING_LOGS:
                t_state += time.perf_counter() - t0

            # Auto-disable only if NOT manually started
            if klip_state != "printing" and not state["manual_override"]:
                if state["monitoring_active"]:
                    logging.info("Printer not printing → Monitoring OFF")
                state["monitoring_active"] = False
                state["action_triggered"] = False

            # If printer just entered printing state, clear old flags
            if klip_state == "printing" and state.get("_last_state") != "printing":
                # DO NOT auto-enable — just reset tracking variables
                state["action_triggered"] = False

            # Monitoring enabled only by macro/api
            ai_enabled = state["monitoring_active"]

            # Track last printer state
            state["_last_state"] = klip_state

            masks_cfg = config.get("masks", {})
            max_frame_score = 0.0
            raw_max_score = 0.0
            failure_cam = None

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
                    # 1. CAMERA READINESS CHECK
                    if not camera_ready.get(cam_id, False):
                        ok = wait_for_camera(cam_id, cam["url"], timeout_seconds=8)
                        if not ok:
                            # Camera never came ready → no error yet, but skip frame
                            state["cameras"][cam_id]["score"] = 0.0
                            state["cameras"][cam_id]["frame"] = None
                            continue   # <-- only skip WHILE waiting
                    # If ready once, NEVER skip the block again

                    # 2. NORMAL FRAME FETCH
                    sess = CAM_SESSIONS.get(cam_id, requests)
                    
                    if ENABLE_TIMING_LOGS:
                        t0 = time.perf_counter()

                    r = sess.get(cam["url"], timeout=1.5)

                    if ENABLE_TIMING_LOGS:
                        t_cameras += time.perf_counter() - t0
                    
                    if r.status_code != 200:
                        raise ValueError(f"HTTP {r.status_code}")

                    # --- APPLY MASKS AND RUN AI ---
                    
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

                    if not ai_enabled:
                        state["cameras"][cam_id]["frame"] = debug
                        continue

                    # Run AI (skipped on some loops, reuse last result)
                    if do_infer:
                        if ENABLE_TIMING_LOGS:
                            t0 = time.perf_counter()

                        score, dets = run_inference(img)

                        if ENABLE_TIMING_LOGS:
                            t_infer += time.perf_counter() - t0

                        # Cache results
                        last_inference[cam_id]["score"] = score
                        last_inference[cam_id]["dets"] = dets
                    else:
                        # Reuse last inference result
                        cached = last_inference.get(cam_id, {})
                        score = cached.get("score", 0.0)
                        dets = cached.get("dets", [])

                    categories = config.get("ai_categories", {})

                    # For failure logic...
                    triggered_here = False
                    trigger_conf_here = 0.0
                    triggered_categories = set()
                    triggered_instance_count = 0

                    if ENABLE_TIMING_LOGS:
                        t0_draw = time.perf_counter()
                    
                    history_best_conf = 0.0
                    history_best_category = None
                    history_is_trigger = False
                    filtered_dets = []
                    for d in dets:
                        x, y, ww, hh = d["box"]
                        conf = float(d["conf"])
                        cid = d["class"]

                        label = CLASS_NAMES[cid] if cid < len(CLASS_NAMES) else "FAIL"
                        key = label.lower()

                        cat_cfg = categories.get(key)
                        if not cat_cfg or not cat_cfg.get("enabled", True):
                            continue

                        detect_thresh = float(cat_cfg["detect_threshold"])
                        trigger_thresh = float(cat_cfg["trigger_threshold"])

                        if conf < detect_thresh:
                            continue

                        filtered_dets.append(d)
                        
                        if conf > history_best_conf:
                            history_best_conf = conf
                            history_best_category = key

                        # per-category detections (only count on real inference)
                        if do_infer:
                            stats_block = state["stats"].get(cam_id)
                            if stats_block is not None:
                                per_cat = stats_block.get("per_category", {})
                                if key in per_cat:
                                    per_cat[key]["detections"] = per_cat[key].get("detections", 0) + 1

                        if cat_cfg.get("trigger", False) and conf >= trigger_thresh:
                            box_color = (0, 0, 255)
                            text_color = (255, 255, 255)
                            triggered_here = True
                            trigger_conf_here = max(trigger_conf_here, conf)
                            triggered_categories.add(key)
                            triggered_instance_count += 1
                            history_is_trigger = True
                        else:
                            box_color = (0, 255, 255)
                            text_color = (0, 0, 0)

                        # Draw detection
                        cv2.rectangle(debug, (x, y), (x+ww, y+hh), box_color, 2)

                        text = f"{label} {int(conf*100)}%"
                        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                        ty = y - 5 if y > 20 else y + th + 5
                        cv2.rectangle(debug, (x, ty-th-2), (x+tw, ty+2), box_color, -1)
                        cv2.putText(debug, text, (x, ty),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, text_color, 1)
                    
                    if do_infer and history_best_category and not state["action_triggered"]:
                        FAILURE_HISTORY.append({
                            "time": time.strftime("%H:%M:%S"),
                            "camera": cam_id,
                            "category": history_best_category,
                            "confidence": int(history_best_conf * 100),
                            "severity": "trigger" if history_is_trigger else "detect"
                        })

                        if len(FAILURE_HISTORY) > MAX_FAILURE_HISTORY:
                            FAILURE_HISTORY.pop(0)
                    
                    if ENABLE_TIMING_LOGS:
                        t_draw += time.perf_counter() - t0_draw
                    
                    if len(filtered_dets) > 0:
                        if do_infer:
                            state["stats"][cam_id]["detections"] += len(filtered_dets)
                        cam_score = max(float(d["conf"]) for d in filtered_dets)
                        state["cameras"][cam_id]["score"] = cam_score
                        raw_max_score = max(raw_max_score, cam_score)
                    else:
                        state["cameras"][cam_id]["score"] = 0.0

                    # For failure logic we track the best "triggerable" confidence
                    if triggered_here and trigger_conf_here > max_frame_score:
                        max_frame_score = trigger_conf_here
                        failure_cam = cam_id

                    if triggered_here and do_infer:
                        state["stats"][cam_id]["failures"] += triggered_instance_count

                        # --- Per-category failure counts ---
                        stats_block = state["stats"].get(cam_id)
                        if stats_block is not None:
                            per_cat = stats_block.get("per_category", {})
                            for cat_key in triggered_categories:
                                if cat_key in per_cat:
                                    per_cat[cat_key]["failures"] = per_cat[cat_key].get("failures", 0) + 1

                    state["cameras"][cam_id]["frame"] = debug

                except Exception as e:
                    # Only log errors AFTER the camera succeeded at least once
                    if camera_ready.get(cam_id, False):
                        logging.error(f"Camera {cam_id} error: {e}")

                    state["cameras"][cam_id]["score"] = 0.0
                    state["cameras"][cam_id]["frame"] = None
                    continue

            # Status machine
            if not ai_enabled:
                state["status"] = "idle"
                state["failure_count"] = 0
                state["action_triggered"] = False
                time.sleep(1)
                continue

            # If failure already triggered, freeze state
            if state["action_triggered"]:
                state["status"] = "failure_detected"
                time.sleep(0.5)
                continue

            state["status"] = "monitoring"
            retries = int(config["consecutive_failures"])

            if do_infer and max_frame_score > 0.0:
                if state["failure_count"] < retries:
                    state["failure_count"] += 1

                logging.info(
                    f"Potential failure: {max_frame_score:.2f} "
                    f"(retry {state['failure_count']}/{retries})"
                )

                if state["failure_count"] >= retries:
                    state["status"] = "failure_detected"
                    state["failure_cam"] = failure_cam
                    state["failure_reason"] = {
                        "category": key,
                        "confidence": trigger_conf_here
                    }
                    
                    logging.info(
                        f"[FAILURE] {key.capitalize()} @ {int(trigger_conf_here * 100)}% | Cam {failure_cam}"
                    )
                    
                    FAILURE_HISTORY.append({
                        "time": time.strftime("%H:%M:%S"),
                        "camera": failure_cam,
                        "category": "FULL FAILURE TRIGGERED",
                        "confidence": int(trigger_conf_here * 100),
                        "severity": "failure"
                    })
                    
                    trigger_printer_action("AI detection")

            elif do_infer and max_frame_score == 0.0:
                if state["failure_count"] > 0:
                    state["failure_count"] -= 1


        except Exception as e:
            logging.error(f"Loop error: {e}")

        interval_s = float(config.get("check_interval", 500)) / 1000.0
        elapsed = time.perf_counter() - loop_start
        
        if ENABLE_TIMING_LOGS:
            total = elapsed
            logging.info(
                f"[TIMING] loop={total*1000:.1f}ms | "
                f"state={t_state*1000:.1f}ms | "
                f"cam={t_cameras*1000:.1f}ms | "
                f"infer={t_infer*1000:.1f}ms | "
                f"draw={t_draw*1000:.1f}ms"
            )
        
        sleep_s = interval_s - elapsed
        if sleep_s > 0:
            time.sleep(sleep_s)
        else:
            time.sleep(0.001)

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
        "max_retries": config["consecutive_failures"],
        "cam_stats": state["stats"],
        "failure_cam": state.get("failure_cam"),
        "failure_reason": state.get("failure_reason")
    })
    
# ================================================================
#   FAILURE HISTORY API
# ================================================================

@app.route("/api/failure_history")
def api_failure_history():
    return jsonify({"events": FAILURE_HISTORY})


@app.route("/api/failure_history/clear", methods=["POST"])
def api_clear_failure_history():
    FAILURE_HISTORY.clear()
    logging.info("Failure history cleared")
    return jsonify({"success": True})

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
