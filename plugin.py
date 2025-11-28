import json
import threading
import time
import base64
import io
from PIL import Image, ImageDraw
from flask import Flask, request, jsonify, send_file
import requests
import cv2
import numpy as np
import os

app = Flask(__name__)

SETTINGS_FILE = "user_settings.json"

DEFAULT_CONFIG = {
    "camera_count": 2,
    "cameras": [
        {"url": "", "enabled": True},
        {"url": "", "enabled": True}
    ],
    "moonraker_url": "http://127.0.0.1:7125",
    "check_interval": 500,
    "warn_threshold": 0.30,
    "ai_threshold": 0.50,
    "consecutive_failures": 3,
    "on_failure": "pause",
    "masks": {"0": [], "1": []},
    "aspect_ratio": "16:9",
    "auto_enable": False  # NEW FEATURE
}

monitor_state = {
    "status": "idle",
    "score": 0.0,
    "failures": 0,
    "max_retries": DEFAULT_CONFIG["consecutive_failures"],
    "monitoring_active": False,
    "show_mask": False
}

lock = threading.Lock()


# Load / Save settings -----------------------------------------

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        save_settings(DEFAULT_CONFIG)
        return DEFAULT_CONFIG
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except:
        return DEFAULT_CONFIG


def save_settings(cfg):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(cfg, f, indent=4)


config = load_settings()


# Camera Fetching ------------------------------------------------

def fetch_image(cam_url):
    if not cam_url:
        return None
    try:
        resp = requests.get(cam_url, timeout=2)
        img_bytes = resp.content
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        return img
    except:
        return None


# Mask Overlay ----------------------------------------------------

def apply_mask_overlay(img, mask_list):
    if not mask_list:
        return img

    draw = ImageDraw.Draw(img, "RGBA")
    w, h = img.size

    for zone in mask_list:
        x = int(zone["x"] * w)
        y = int(zone["y"] * h)
        ww = int(zone["w"] * w)
        hh = int(zone["h"] * h)
        draw.rectangle([x, y, x + ww, y + hh], fill=(255, 0, 255, 80))

    return img


# Background Monitoring Thread -----------------------------------

def background_monitor():
    global config, monitor_state

    while True:
        time.sleep(max(0.1, config.get("check_interval", 500) / 1000.0))

        with lock:
            moonraker = config.get("moonraker_url", "http://127.0.0.1:7125")
            try:
                r = requests.get(f"{moonraker}/printer/objects/query?print_stats", timeout=2)
                pr_state = r.json()["result"]["status"]["print_stats"]["state"]
            except:
                pr_state = "error"

            auto_enable = config.get("auto_enable", False)
            manual_active = monitor_state["monitoring_active"]

            # Decide if monitoring should run -----------------------------------
            if auto_enable:
                # Only active WHILE printing (auto)
                should_run = (pr_state == "printing")
            else:
                # Manual mode / previous logic
                should_run = (pr_state in ["printing", "paused"]) or manual_active

            # Reset manual flag when not printing -------------------------------
            if pr_state != "printing":
                monitor_state["monitoring_active"] = False

            if not should_run:
                monitor_state["status"] = "idle"
                monitor_state["score"] = 0.0
                monitor_state["failures"] = 0
                continue

            monitor_state["status"] = "monitoring"

        # PROCESS ALL ENABLED CAMERAS -----------------------------------------
        worst_score = 0.0
        failure_detected = False

        for cam_id, cam in enumerate(config["cameras"]):
            if not cam["enabled"]:
                continue

            img = fetch_image(cam["url"])
            if img is None:
                continue

            # Convert to OpenCV
            cv_img = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

            # Dummy detection calculation
            fail_score = float(np.mean(cv_img)) / 255.0

            if fail_score > worst_score:
                worst_score = fail_score

            if fail_score >= config.get("ai_threshold", 0.50):
                failure_detected = True

        with lock:
            monitor_state["score"] = worst_score

            warn_t = config.get("warn_threshold", 0.30)
            fail_t = config.get("ai_threshold", 0.50)

            if failure_detected:
                monitor_state["failures"] += 1
            else:
                monitor_state["failures"] = 0

            max_r = config.get("consecutive_failures", 3)
            monitor_state["max_retries"] = max_r

            if monitor_state["failures"] >= max_r:
                monitor_state["status"] = "failure_detected"
                if config.get("on_failure") == "pause":
                    try:
                        requests.post(f"{moonraker}/printer/print/pause")
                    except:
                        pass
                elif config.get("on_failure") == "cancel":
                    try:
                        requests.post(f"{moonraker}/printer/print/cancel")
                    except:
                        pass

                monitor_state["monitoring_active"] = False


threading.Thread(target=background_monitor, daemon=True).start()


# API ROUTES -------------------------------------------------------

@app.route("/api/status")
def api_status():
    with lock:
        return jsonify(monitor_state)


@app.route("/api/frame/<cam_id>")
def api_frame(cam_id):
    cam_id = int(cam_id)

    if cam_id >= len(config["cameras"]):
        return "", 404

    cam = config["cameras"][cam_id]
    img = fetch_image(cam["url"])
    if img is None:
        return "", 404

    if monitor_state["show_mask"]:
        mask_list = config.get("masks", {}).get(str(cam_id), [])
        img = apply_mask_overlay(img, mask_list)

    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    buf.seek(0)

    return send_file(buf, mimetype='image/jpeg')


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    global config
    if request.method == "POST":
        new_cfg = request.json
        config = new_cfg
        save_settings(config)
        return jsonify({"ok": True})

    return jsonify(config)


@app.route("/api/action/start", methods=["POST"])
def api_start():
    with lock:
        monitor_state["monitoring_active"] = True
        monitor_state["failures"] = 0
        monitor_state["status"] = "monitoring"
    return jsonify({"ok": True})


@app.route("/api/action/stop", methods=["POST"])
def api_stop():
    with lock:
        monitor_state["monitoring_active"] = False
        monitor_state["status"] = "idle"
        monitor_state["failures"] = 0
    return jsonify({"ok": True})


@app.route("/api/action/toggle_mask", methods=["POST"])
def api_toggle_mask():
    data = request.json
    show = data.get("show", False)
    monitor_state["show_mask"] = show
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7126, debug=False)
