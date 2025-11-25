let imageInterval; // Store the interval ID so we can stop/start it

// DOM Elements
const liveImage = document.getElementById('live-image');
const debugToggle = document.getElementById('debug-toggle');
const statusBadge = document.getElementById('status-indicator');
const settingsModal = document.getElementById('settings-modal');
const ssimText = document.getElementById('ssim-val');
const retryText = document.getElementById('retry-val');
const confidenceBar = document.getElementById('confidence-bar');
const camContainer = document.getElementById('camera-container');

// --- DYNAMIC IMAGE REFRESH LOOP ---
function startImageLoop(rate) {
    // Stop the old loop if it exists
    if (imageInterval) clearInterval(imageInterval);
    
    // Safety: Default to 500ms if invalid or too fast (<100ms)
    const safeRate = (rate && rate >= 100) ? rate : 500;
    
    imageInterval = setInterval(() => {
        const timestamp = new Date().getTime();
        // Choose endpoint based on toggle: Normal or Debug (Mask)
        const endpoint = debugToggle.checked ? '/api/debug_frame' : '/api/latest_frame';
        liveImage.src = `${endpoint}?t=${timestamp}`;
    }, safeRate);
}

// Start with default, will update when settings load
startImageLoop(500);

// --- STATUS LOOP (Always 1 second) ---
async function updateStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        // 1. Update Badge Text
        statusBadge.innerText = data.status.toUpperCase();
        
        // 2. Update Badge Color based on State
        if (data.status === 'failure_detected' || data.status === 'error') {
            statusBadge.style.backgroundColor = '#F44336'; // Red
        } else if (data.status === 'monitoring') {
            statusBadge.style.backgroundColor = '#4CAF50'; // Green
        } else if (data.status === 'idle') {
            statusBadge.style.backgroundColor = '#555555'; // Grey (IDLE)
        } else if (data.status === 'connection_error') {
            statusBadge.style.backgroundColor = '#9E9E9E'; // Lighter Grey
        } else {
            statusBadge.style.backgroundColor = '#f39c12'; // Orange (Checking)
        }

        // 3. Update Health Bar
        const ssimPercent = Math.round(data.ssim * 100);
        ssimText.innerText = `${ssimPercent}%`;
        retryText.innerText = `${data.failures}/${data.max_retries}`;
        confidenceBar.style.width = `${ssimPercent}%`;

        // Bar Color Logic
        if (data.failures > 0) {
             confidenceBar.style.background = '#FF5722'; // Orange/Red warning
        } else if (data.ssim < 0.90) {
             confidenceBar.style.background = '#FFC107'; // Yellow warning
        } else {
             confidenceBar.style.background = 'linear-gradient(90deg, #4CAF50, #8BC34A)'; // Green
        }

    } catch (e) { console.log("Status error", e); }
}
setInterval(updateStatus, 1000);

// --- SETTINGS MANAGEMENT ---
document.getElementById('open-settings-btn').addEventListener('click', async () => {
    // Fetch current settings from backend
    const res = await fetch('/api/settings');
    const data = await res.json();
    
    // Populate Inputs
    document.getElementById('camera_url').value = data.camera_url;
    document.getElementById('moonraker_url').value = data.moonraker_url || "http://127.0.0.1:7125";
    document.getElementById('check_interval').value = data.check_interval;
    document.getElementById('ssim_threshold').value = data.ssim_threshold;
    document.getElementById('mask_margin').value = data.mask_margin;
    document.getElementById('consecutive_failures').value = data.consecutive_failures;
    document.getElementById('on_failure').value = data.on_failure || "nothing";
    document.getElementById('aspect_ratio').value = data.aspect_ratio || "16:9";
    document.getElementById('preview_refresh_rate').value = data.preview_refresh_rate || 500;
    
    // Apply visual aspect ratio immediately so the user sees current state
    if(data.aspect_ratio) {
        camContainer.style.aspectRatio = data.aspect_ratio.replace(':', '/');
    }

    settingsModal.showModal();
});

document.getElementById('close-modal-x').addEventListener('click', () => {
    settingsModal.close();
});

document.getElementById('save-settings-btn').addEventListener('click', async () => {
    // Capture the new refresh rate to apply it immediately
    const newRate = parseInt(document.getElementById('preview_refresh_rate').value);
    
    const payload = {
        camera_url: document.getElementById('camera_url').value,
        moonraker_url: document.getElementById('moonraker_url').value,
        
        // Parse as Integer (ms)
        check_interval: parseInt(document.getElementById('check_interval').value),
        
        ssim_threshold: parseFloat(document.getElementById('ssim_threshold').value),
        mask_margin: parseInt(document.getElementById('mask_margin').value),
        consecutive_failures: parseInt(document.getElementById('consecutive_failures').value),
        on_failure: document.getElementById('on_failure').value,
        aspect_ratio: document.getElementById('aspect_ratio').value,
        preview_refresh_rate: newRate
    };
    
    // Send to Python
    await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    
    // Apply visual changes locally immediately
    camContainer.style.aspectRatio = payload.aspect_ratio.replace(':', '/');
    startImageLoop(newRate); 
    
    alert("Configuration Saved!");
    settingsModal.close();
});

// INITIAL LOAD
// We fetch settings once on page load to set the Aspect Ratio and Refresh Rate 
// without needing the user to open the menu.
fetch('/api/settings').then(r => r.json()).then(data => {
    if(data.aspect_ratio) camContainer.style.aspectRatio = data.aspect_ratio.replace(':', '/');
    if(data.preview_refresh_rate) startImageLoop(data.preview_refresh_rate);
});
