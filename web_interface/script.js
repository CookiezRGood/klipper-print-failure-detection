async function loadSettings() {
    try {
        const response = await fetch('/api/settings');
        const data = await response.json();
        document.getElementById('ssim_threshold').value = data.ssim_threshold;
        document.getElementById('stillness_threshold').value = data.stillness_threshold;
        if(data.camera_url) {
            document.getElementById('camera-container').innerHTML = `<img src="${data.camera_url}" class="live-feed">`;
        }
    } catch (error) { console.error(error); }
}

async function checkStatus() {
    try {
        const response = await fetch('/api/failure_status');
        const data = await response.json();
        const badge = document.getElementById('status-indicator');
        badge.innerText = data.status.toUpperCase();
        badge.style.backgroundColor = data.status === 'active' ? '#4CAF50' : '#f39c12';
    } catch (error) { console.error(error); }
}

document.getElementById('save-btn').addEventListener('click', async () => {
    const ssim = parseFloat(document.getElementById('ssim_threshold').value);
    const stillness = parseFloat(document.getElementById('stillness_threshold').value);
    await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ssim_threshold: ssim, stillness_threshold: stillness })
    });
    alert('Settings Saved!');
});

loadSettings();
setInterval(checkStatus, 2000);
