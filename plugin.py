import logging
from flask import Flask, jsonify, request, send_from_directory
import threading
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logging.info("Starting the Print Failure Detection Plugin...")

# Initialize Flask app
# We tell Flask that the "static" folder is your "web_interface" folder
app = Flask(__name__, static_folder='web_interface')

# Sample plugin configuration
current_config = {
    "ssim_threshold": 0.97,
    "stillness_threshold": 0.20,
    "layer_min_step": 0.15,
    "camera_url": "http://192.168.10.153/webcam/?action=snapshot"
}

# --- NEW: Route to serve the UI ---
@app.route('/')
def serve_index():
    # This serves the index.html from your web_interface folder
    return send_from_directory('web_interface', 'index.html')

# Serve other static files (JS/CSS) if they are requested
@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('web_interface', path)
# ----------------------------------

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    global current_config
    if request.method == 'POST':
        data = request.json
        current_config.update(data)
    return jsonify(current_config)

@app.route('/api/failure_status', methods=['GET'])
def failure_status():
    status = {
        "status": "active" 
    }
    return jsonify(status)

def run_plugin():
    logging.info("Running Flask app on port 7126...")
    app.run(host='0.0.0.0', port=7126, threaded=True)

if __name__ == "__main__":
    run_plugin()
