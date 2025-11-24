const REFRESH_RATE = 500; // Update image twice a second

const liveImage = document.getElementById('live-image');
const debugToggle = document.getElementById('debug-toggle');
const statusBadge = document.getElementById('status-indicator');
const settingsModal = document.getElementById('settings-modal');

// New UI Elements
const ssimText = document.getElementById('ssim-val');
const retryText = document.getElementById('retry-val');
const confidenceBar = document.getElementById('confidence-bar');

function refreshImage() {
    const timestamp = new Date().getTime();
    const endpoint = debugToggle.checked ? '/api/debug_frame' : '/api/latest_frame';
    liveImage.src = `${endpoint}?t=${timestamp}`;
}
setInterval(refreshImage, REFRESH_RATE);

// Update Status & Health Bar
async function updateStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        // 1. Update Status Badge
        statusBadge.innerText = data.status.toUpperCase();
        if (data.status === 'failure_detected') statusBadge.style.backgroundColor = '#F44336'; // Red
        else if (data.status === 'monitoring') statusBadge.style.backgroundColor = '#4CAF50'; // Green
        else statusBadge.style.backgroundColor = '#f39c12'; // Orange/Checking

        // 2. Update Health Bar
        const ssimPercent = Math.round(data.ssim * 100);
        ssimText.innerText = `${ssimPercent}%`;
        retryText.innerText = `${data.failures}/${data.max_retries}`;

        // Bar Length (SSIM)
        confidenceBar.style.width = `${ssimPercent}%`;

        // Bar Color Logic
        if (data.failures > 0) {
            // If we are retrying, turn bar Orange/Red
             confidenceBar.style.background = '#FF5722'; 
        } else if (data.ssim < 0.90) {
             confidenceBar.style.background = '#FFC107'; // Warning Yellow
        } else {
             confidenceBar.style.background = 'linear-gradient(90deg, #4CAF50, #8BC34A)'; // Healthy Green
        }

    } catch (e) { console.log("Status error", e); }
}
setInterval(updateStatus, 1000);

// --- Settings Modal Logic ---
document.getElementById('open-settings-btn').addEventListener('click', async () => {
    const res = await fetch('/api/settings');
    const data = await res.json();
    document.getElementById('ssim_threshold').value = data.ssim_threshold;
    document.getElementById('mask_margin').value = data.mask_margin || 15;
    document.getElementById('consecutive_failures').value = data.consecutive_failures || 3;
    settingsModal.showModal();
});

document.getElementById('close-modal-x').addEventListener('click', () => settingsModal.close());

document.getElementById('save-settings-btn').addEventListener('click', async () => {
    const payload = {
        ssim_threshold: parseFloat(document.getElementById('ssim_threshold').value),
        mask_margin: parseInt(document.getElementById('mask_margin').value),
        consecutive_failures: parseInt(document.getElementById('consecutive_failures').value)
    };
    await fetch('/api/settings', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
    });
    settingsModal.close();
});
