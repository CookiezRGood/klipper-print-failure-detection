let imageInterval;

// Settings and toggles
let currentSettings = {};
let isMaskVisible = false;
let suppressConfidenceUpdates = false;

const statusBadge = document.getElementById('status-indicator');
const ssimText = document.getElementById('ssim-val');
const retryText = document.getElementById('retry-val');
const confidenceBar = document.getElementById('confidence-bar');
const forceStartBtn = document.getElementById('force-start-btn');
const maskToggleBtn = document.getElementById('mask-toggle-btn');
const settingsModal = document.getElementById('settings-modal');
const overlay = document.getElementById('settings-overlay');

const mainContent = document.getElementById('main-content');

const cameraGrid = document.getElementById('camera-grid');

// Camera references
const cam1Img = document.getElementById('cam1-img');
const cam2Img = document.getElementById('cam2-img');

[cam1Img, cam2Img].forEach(img => {
    if (!img) return;

    img.setAttribute('draggable', 'false');
    img.draggable = false;
    img.style.userSelect = 'none';

    img.addEventListener('mousedown', e => e.preventDefault());
});

const cam1Card = document.getElementById('card-cam1');
const cam2Card = document.getElementById('card-cam2');
const cam1Toggle = document.getElementById('cam1-toggle');
const cam2Toggle = document.getElementById('cam2-toggle');
const cam1View = document.getElementById('cam1-container');
const cam2View = document.getElementById('cam2-container');

// Mask clearing
const cam1ClearBtn = document.getElementById('cam1-clear-masks');
const cam2ClearBtn = document.getElementById('cam2-clear-masks');

// Mask zones for each camera
const maskZones = { 0: [], 1: [] };

// Clear masks
if (cam1ClearBtn) {
    cam1ClearBtn.addEventListener('click', () => {
        maskZones[0] = [];
        syncMasksToServer();
    });
}
if (cam2ClearBtn) {
    cam2ClearBtn.addEventListener('click', () => {
        maskZones[1] = [];
        syncMasksToServer();
    });
}

/********************************************************************
 * Image Loop
 ********************************************************************/
function startImageLoop(rate) {
    if (imageInterval) clearInterval(imageInterval);

    const finalRate = (rate && rate >= 100) ? rate : 500;

    imageInterval = setInterval(() => {
        const now = Date.now();

        cam1Img.src = cam1Card.classList.contains('disabled') ? "" : `/api/frame/0?cache_bust=${now}`;
        cam2Img.src = cam2Card.classList.contains('disabled') ? "" : `/api/frame/1?cache_bust=${now}`;

    }, finalRate);
}

/********************************************************************
 * Camera toggle
 ********************************************************************/
async function toggleCamera(camId, enabled) {
    const card = camId === 0 ? cam1Card : cam2Card;
    const toggle = camId === 0 ? cam1Toggle : cam2Toggle;

    toggle.checked = enabled;

    if (enabled) card.classList.remove('disabled');
    else card.classList.add('disabled');

    if (currentSettings.cameras) {
        currentSettings.cameras[camId].enabled = enabled;

        try {
            await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(currentSettings)
            });
        } catch (err) {}
    }
}

cam1Toggle.addEventListener('change', ev => toggleCamera(0, ev.target.checked));
cam2Toggle.addEventListener('change', ev => toggleCamera(1, ev.target.checked));

/********************************************************************
 * Monitoring button
 ********************************************************************/
function setButtonState(mode) {
    forceStartBtn.classList.remove('btn-success', 'btn-danger');

    if (mode === 'start') {
        forceStartBtn.innerText = "▶ Start Monitoring";
        forceStartBtn.classList.add('btn-success');
        forceStartBtn.dataset.action = "start";
    } else {
        forceStartBtn.innerText = "■ Stop Monitoring";
        forceStartBtn.classList.add('btn-danger');
        forceStartBtn.dataset.action = "stop";
    }
}

forceStartBtn.addEventListener('click', async () => {
    const action = forceStartBtn.dataset.action;

    try {
        await fetch(`/api/action/${action}`, { method: 'POST' });
    } catch (err) {}

    setTimeout(updateStatus, 150);
});

/********************************************************************
 * Status polling
 ********************************************************************/
async function updateStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        
        // Per-camera detection & failure counters
        if (data.cam_stats) {
            document.getElementById("cam1-detect-count").innerText =
                data.cam_stats["0"].detections;

            document.getElementById("cam1-fail-count").innerText =
                data.cam_stats["0"].failures;

            document.getElementById("cam2-detect-count").innerText =
                data.cam_stats["1"].detections;

            document.getElementById("cam2-fail-count").innerText =
                data.cam_stats["1"].failures;
        }
        
        // Store for stats modal
        lastCamStats = data.cam_stats;
        refreshStatsModalIfOpen();

        const statusTxt = data.status.toUpperCase().replace('_', ' ');
        statusBadge.innerText = statusTxt;

        if (data.status === 'failure_detected') {
            statusBadge.style.backgroundColor = '#e53935';
            setButtonState('stop');
        } else if (data.status === 'monitoring') {
            statusBadge.style.backgroundColor = '#43a047';
            setButtonState('stop');
        } else {
            statusBadge.style.backgroundColor = '#555';
            setButtonState('start');
        }

        // Fade out health UI when not monitoring
        const health = document.querySelector('.health-section');

        if (data.status !== 'monitoring' && data.status !== 'failure_detected') {
            health.classList.add('dimmed');

            confidenceBar.style.opacity = "0";

            setTimeout(() => {
                confidenceBar.style.width = "0%";
                confidenceBar.style.backgroundColor = "#4CAF50";
                ssimText.innerText = "0%";
                retryText.innerText = `0/${data.max_retries}`;
            }, 400);

            const label = document.getElementById("monitoring-label");
            label.textContent = "Not Monitoring";
            label.style.opacity = "1";

            suppressConfidenceUpdates = true;

        } else {
            health.classList.remove('dimmed');
            confidenceBar.style.opacity = "1";

            const label = document.getElementById("monitoring-label");
            label.style.opacity = "0";

            suppressConfidenceUpdates = false;
        }

        if (!suppressConfidenceUpdates) {
            const failPct = Math.round(data.score * 100);
            ssimText.innerText = failPct + '%';
            retryText.innerText = `${data.failures}/${data.max_retries}`;
            confidenceBar.style.width = failPct + '%';

            // Find trigger thresholds for categories that can cancel the print
            const cats = currentSettings.ai_categories || {};
            const detectThresholds = [];
            const triggerThresholds = [];

            Object.values(cats).forEach(c => {
                if (!c || !c.enabled) return;

                detectThresholds.push((c.detect_threshold ?? 0.3) * 100);

                if (c.trigger) {
                    triggerThresholds.push((c.trigger_threshold ?? 0.7) * 100);
                }
            });

            // “Warning” point: the lowest detect threshold among enabled categories
            const warnT = detectThresholds.length > 0 ? Math.min(...detectThresholds) : 100;

            // “Failure” point: the lowest trigger threshold among enabled+trigger categories
            const failT = triggerThresholds.length > 0 ? Math.min(...triggerThresholds) : 100;

            // Compute color
            let barColor;

            if (failPct >= failT) {
                barColor = '#F44336'; // red = above failure threshold
            } else {
                const range = failT - warnT;
                const relative = (failPct - warnT) / range;

                if (relative < 0) barColor = '#4CAF50';          // green
                else if (relative < 0.33) barColor = '#4CAF50'; // green
                else if (relative < 0.66) barColor = '#FFEB3B'; // yellow
                else barColor = '#FFB74D';                       // orange
            }

            confidenceBar.style.backgroundColor = barColor;

        }

    } catch (err) {}
}

setInterval(updateStatus, 1200);

/********************************************************************
 * Mask toggle
 ********************************************************************/
maskToggleBtn.addEventListener('click', async () => {
    isMaskVisible = !isMaskVisible;

    maskToggleBtn.style.backgroundColor = isMaskVisible ? "#2196F3" : "";
    maskToggleBtn.style.color = isMaskVisible ? "white" : "";

    try {
        await fetch('/api/action/toggle_mask', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({ show: isMaskVisible })
        });
    } catch (err) {}
});

/********************************************************************
 * Layout switching
 ********************************************************************/
function applyLayout(count) {
    if (parseInt(count) === 1) {
        cameraGrid.classList.add('single-mode');
        cam2Card.classList.add('hidden');
    } else {
        cameraGrid.classList.remove('single-mode');
        cam2Card.classList.remove('hidden');
    }
}

/********************************************************************
 * Sync mask zones
 ********************************************************************/
function syncMasksToServer() {
    currentSettings.masks = {
        "0": maskZones[0],
        "1": maskZones[1]
    };

    fetch('/api/settings', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(currentSettings)
    });
    
    updateMaskIndicators();
}

/********************************************************************
 * Mask drawing
 ********************************************************************/
function setupMaskDrawing(camId, viewEl) {

    viewEl.classList.add("mask-draw-enabled");
    let drawing = false;
    let startX = 0, startY = 0;
    let tempRect = null;

    function posInCam(e) {
        const r = viewEl.getBoundingClientRect();
        return {
            x: e.clientX - r.left,
            y: e.clientY - r.top,
            w: r.width,
            h: r.height
        };
    }

    viewEl.addEventListener('mousedown', (ev) => {
        ev.preventDefault();
        if (ev.button !== 0) return;

        const { x, y, w, h } = posInCam(ev);
        if (x < 0 || y < 0 || x > w || y > h) return;

        drawing = true;
        startX = x;
        startY = y;

        tempRect = document.createElement('div');
        tempRect.classList.add('temp-mask-rect');
        Object.assign(tempRect.style, {
            position:'absolute',
            border:'1px solid #ff00ff',
            backgroundColor:'rgba(255,0,255,0.20)',
            left:`${x}px`,
            top:`${y}px`,
            pointerEvents:'none'
        });

        viewEl.appendChild(tempRect);
    });

    window.addEventListener('mousemove', (ev) => {
        if (!drawing || !tempRect) return;
        const { x, y } = posInCam(ev);

        const minX = Math.min(startX, x);
        const minY = Math.min(startY, y);
        const w = Math.abs(x - startX);
        const h = Math.abs(y - startY);

        Object.assign(tempRect.style, {
            left:`${minX}px`,
            top:`${minY}px`,
            width:`${w}px`,
            height:`${h}px`
        });
    });

    window.addEventListener('mouseup', (ev) => {
        if (!drawing || !tempRect) return;

        const { x, y, w, h } = posInCam(ev);

        const rx = Math.min(startX, x);
        const ry = Math.min(startY, y);
        const rw = Math.abs(x - startX);
        const rh = Math.abs(y - startY);

        tempRect.remove();
        drawing = false;
        tempRect = null;

        if (rw < 10 || rh < 10) return;

        maskZones[camId].push({
            x: rx / w,
            y: ry / h,
            w: rw / w,
            h: rh / h
        });

        syncMasksToServer();
    });

    viewEl.addEventListener('contextmenu', (ev) => {
        ev.preventDefault();

        const { x, y, w, h } = posInCam(ev);
        const nx = x / w;
        const ny = y / h;

        const zones = maskZones[camId];

        for (let i = zones.length - 1; i >= 0; i--) {
            const z = zones[i];
            if (
                nx >= z.x &&
                ny >= z.y &&
                nx <= z.x + z.w &&
                ny <= z.y + z.h
            ) {
                zones.splice(i, 1);
                syncMasksToServer();
                return;
            }
        }
    });
}

function updateMaskIndicators() {
    [0, 1].forEach(camId => {
        const view = camId === 0 ? cam1View : cam2View;
        const zones = maskZones[camId] || [];

        if (!view) return;

        if (zones.length > 0) {
            // Add indicator
            if (!view.classList.contains("has-masks")) {
                view.classList.add("has-masks");

                // Trigger pulse animation
                view.classList.add("pulse-mask");
                setTimeout(() => {
                    view.classList.remove("pulse-mask");
                }, 2000);
            }
        } else {
            view.classList.remove("has-masks");
            view.classList.remove("pulse-mask");
        }
    });
}

/********************************************************************
 * Load settings
 ********************************************************************/
async function loadSettings() {
    try {
        const resp = await fetch('/api/settings');
        currentSettings = await resp.json();

        const cam1 = currentSettings.cameras[0];
        const cam2 = currentSettings.cameras[1];

        toggleCamera(0, cam1.enabled);
        toggleCamera(1, cam2.enabled);

        // Camera count
        document.getElementById('camera_count').value =
            currentSettings.camera_count || 2;

        // URLs
        document.getElementById('cam1_url_input').value = cam1.url || "";
        document.getElementById('cam2_url_input').value = cam2.url || "";

        // Moonraker URL
        document.getElementById('moonraker_url').value =
            currentSettings.moonraker_url || "";

        // Check interval
        document.getElementById('check_interval').value =
            currentSettings.check_interval || 500;

        // Load category settings
        const cats = currentSettings.ai_categories || {};

        document.getElementById("cat_spaghetti_enabled").checked =
            cats.spaghetti?.enabled ?? true;
        document.getElementById("cat_spaghetti_trigger").checked =
            cats.spaghetti?.trigger ?? true;
        document.getElementById("cat_spaghetti_detect_threshold").value =
            Math.round((cats.spaghetti?.detect_threshold ?? 0.3) * 100);

        document.getElementById("cat_spaghetti_trigger_threshold").value =
            Math.round((cats.spaghetti?.trigger_threshold ?? 0.7) * 100);

        // Blob
        document.getElementById("cat_blob_enabled").checked =
            cats.blob?.enabled ?? true;
        document.getElementById("cat_blob_trigger").checked =
            cats.blob?.trigger ?? false;
        document.getElementById("cat_blob_detect_threshold").value =
            Math.round((cats.blob?.detect_threshold ?? 0.3) * 100);

        document.getElementById("cat_blob_trigger_threshold").value =
            Math.round((cats.blob?.trigger_threshold ?? 0.7) * 100);

        // Crack
        document.getElementById("cat_crack_enabled").checked =
            cats.crack?.enabled ?? true;
        document.getElementById("cat_crack_trigger").checked =
            cats.crack?.trigger ?? false;
        document.getElementById("cat_crack_detect_threshold").value =
            Math.round((cats.crack?.detect_threshold ?? 0.3) * 100);

        document.getElementById("cat_crack_trigger_threshold").value =
            Math.round((cats.crack?.trigger_threshold ?? 0.7) * 100);

        // Warping
        document.getElementById("cat_warping_enabled").checked =
            cats.warping?.enabled ?? true;
        document.getElementById("cat_warping_trigger").checked =
            cats.warping?.trigger ?? false;
        document.getElementById("cat_warping_detect_threshold").value =
            Math.round((cats.warping?.detect_threshold ?? 0.3) * 100);

        document.getElementById("cat_warping_trigger_threshold").value =
            Math.round((cats.warping?.trigger_threshold ?? 0.7) * 100);

        // Failures
        document.getElementById('consecutive_failures').value =
            currentSettings.consecutive_failures || 3;

        // On failure
        document.getElementById('on_failure').value =
            currentSettings.on_failure || "pause";

        // Masks
        const m = currentSettings.masks || {};
        maskZones[0] = Array.isArray(m["0"]) ? [...m["0"]] : [];
        maskZones[1] = Array.isArray(m["1"]) ? [...m["1"]] : [];
        updateMaskIndicators();

        // Per-camera aspect ratios
        document.getElementById('cam1_aspect_ratio').value =
            currentSettings.cam1_aspect_ratio || "4:3";

        document.getElementById('cam2_aspect_ratio').value =
            currentSettings.cam2_aspect_ratio || "4:3";

        // Apply aspect ratios to camera views
        const ratio1 = (currentSettings.cam1_aspect_ratio || "4:3").replace(':',' / ');
        const ratio2 = (currentSettings.cam2_aspect_ratio || "4:3").replace(':',' / ');

        cam1View.style.aspectRatio = ratio1;
        cam2View.style.aspectRatio = ratio2;

        applyLayout(currentSettings.camera_count || 2);
        startImageLoop(currentSettings.check_interval || 500);

    } catch (err) {
        console.error(err);
    }
}

/********************************************************************
 * Open / Close Settings panel (blur + overlay)
 ********************************************************************/
document.getElementById('open-settings-btn').addEventListener('click', () => {
    loadSettings();
    settingsModal.showModal();
    settingsModal.classList.add('show');
    overlay.classList.add('active');
    mainContent.classList.add('blurred');
});

// ===============================
// TWO-PAGE SETTINGS SYSTEM
// ===============================
const settingsPages = document.getElementById("settings-pages");
const openAiBtn = document.getElementById("open-ai-cat-btn");
const backAiBtn = document.getElementById("back-ai-btn");

// Open AI Category Page
openAiBtn.addEventListener("click", () => {
    settingsPages.classList.add("show-ai");
});

// Go back to main settings page
backAiBtn.addEventListener("click", () => {
    settingsPages.classList.remove("show-ai");
});

document.getElementById('close-modal-x').addEventListener('click', () => {
    settingsModal.classList.remove('show');
    settingsPages.classList.remove("show-ai");
    settingsModal.close();
    overlay.classList.remove('active');
    mainContent.classList.remove('blurred');
});

/********************************************************************
 * Per-Category Detection Stats Modal
 ********************************************************************/

// Store latest cam_stats from /api/status
let lastCamStats = null;

// Reference to detection boxes on main dashboard
const cam1StatsCard = document.getElementById("cam1-stats");
const cam2StatsCard = document.getElementById("cam2-stats");

// Stats modal DOM
const statsModal = document.getElementById("stats-modal");
const statsModalTitle = document.getElementById("stats-modal-title");
const statsModalClose = document.getElementById("close-stats-modal");

function fillStatsModal(camId) {
    if (!lastCamStats) return;

    const camKey = String(camId);
    const stats = lastCamStats[camKey];
    if (!stats || !stats.per_category) return;

    statsModalTitle.textContent =
        camId === 0 ? "Primary Camera Detection Breakdown" :
                      "Secondary Camera Detection Breakdown";

    const perCat = stats.per_category;

    function setCounts(key, detId, failId) {
        const detEl = document.getElementById(detId);
        const failEl = document.getElementById(failId);
        if (!detEl || !failEl) return;

        detEl.textContent  = perCat[key]?.detections ?? 0;
        failEl.textContent = perCat[key]?.failures ?? 0;
    }

    setCounts("spaghetti", "stat-det-spaghetti", "stat-fail-spaghetti");
    setCounts("blob",      "stat-det-blob",      "stat-fail-blob");
    setCounts("warping",   "stat-det-warping",   "stat-fail-warping");
    setCounts("crack",     "stat-det-crack",     "stat-fail-crack");
}

function refreshStatsModalIfOpen() {
    if (!statsModal.open) return;

    // Determine which camera modal is showing
    if (statsModalTitle.textContent.includes("Primary")) {
        fillStatsModal(0);
    } else if (statsModalTitle.textContent.includes("Secondary")) {
        fillStatsModal(1);
    }
}

let activeStatsCamId = null;

function openStatsModal(camId) {
    activeStatsCamId = camId;
    fillStatsModal(camId);
    statsModal.showModal();
    statsModal.classList.add("show");
    mainContent.classList.add("blurred");
}

// Make dashboard detection boxes clickable
if (cam1StatsCard) cam1StatsCard.addEventListener("click", () => openStatsModal(0));
if (cam2StatsCard) cam2StatsCard.addEventListener("click", () => openStatsModal(1));

if (statsModalClose) {
    statsModalClose.addEventListener("click", () => {
    statsModal.close();
    setTimeout(() => statsModal.close(), 150);
    mainContent.classList.remove("blurred");
});
}

const resetStatsBtn = document.getElementById("reset-stats-btn");

if (resetStatsBtn) {
    resetStatsBtn.addEventListener("click", async () => {
        if (activeStatsCamId === null) return;

        try {
            await fetch(`/api/stats/reset/${activeStatsCamId}`, {
                method: "POST"
            });
        } catch (err) {
            console.error("Failed to reset stats", err);
            return;
        }

        // Immediately refresh local copy
        if (lastCamStats && lastCamStats[String(activeStatsCamId)]) {
            lastCamStats[String(activeStatsCamId)] = {
                detections: 0,
                failures: 0,
                per_category: {}
            };
        }

        fillStatsModal(activeStatsCamId);
    });
}

/********************************************************************
 * Save settings
 ********************************************************************/
document.getElementById('save-settings-btn').addEventListener('click', async () => {

    currentSettings.camera_count =
        parseInt(document.getElementById('camera_count').value);

    currentSettings.cameras[0].url =
        document.getElementById('cam1_url_input').value;

    currentSettings.cameras[1].url =
        document.getElementById('cam2_url_input').value;

    currentSettings.moonraker_url =
        document.getElementById('moonraker_url').value;

    currentSettings.check_interval =
        parseInt(document.getElementById('check_interval').value);

    currentSettings.consecutive_failures =
        parseInt(document.getElementById('consecutive_failures').value);

    currentSettings.on_failure =
        document.getElementById('on_failure').value;
        
    // Save category settings
    currentSettings.ai_categories = {
    spaghetti: {
        enabled: document.getElementById("cat_spaghetti_enabled").checked,
        trigger: document.getElementById("cat_spaghetti_trigger").checked,
        detect_threshold: document.getElementById("cat_spaghetti_detect_threshold").value / 100,
        trigger_threshold: document.getElementById("cat_spaghetti_trigger_threshold").value / 100
    },
    blob: {
        enabled: document.getElementById("cat_blob_enabled").checked,
        trigger: document.getElementById("cat_blob_trigger").checked,
        detect_threshold: document.getElementById("cat_blob_detect_threshold").value / 100,
        trigger_threshold: document.getElementById("cat_blob_trigger_threshold").value / 100
    },
    crack: {
        enabled: document.getElementById("cat_crack_enabled").checked,
        trigger: document.getElementById("cat_crack_trigger").checked,
        detect_threshold: document.getElementById("cat_crack_detect_threshold").value / 100,
        trigger_threshold: document.getElementById("cat_crack_trigger_threshold").value / 100
    },
    warping: {
        enabled: document.getElementById("cat_warping_enabled").checked,
        trigger: document.getElementById("cat_warping_trigger").checked,
        detect_threshold: document.getElementById("cat_warping_detect_threshold").value / 100,
        trigger_threshold: document.getElementById("cat_warping_trigger_threshold").value / 100
    }
};

    currentSettings.masks = {
        "0": maskZones[0],
        "1": maskZones[1]
    };

    currentSettings.cam1_aspect_ratio =
    document.getElementById("cam1_aspect_ratio").value;

    currentSettings.cam2_aspect_ratio =
        document.getElementById("cam2_aspect_ratio").value;

    await fetch('/api/settings', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(currentSettings)
    });

    // CAM 1 aspect ratio
    if (currentSettings.cam1_aspect_ratio) {
        const ratio1 = currentSettings.cam1_aspect_ratio.replace(':',' / ');
        cam1View.style.aspectRatio = ratio1;
    }

    // CAM 2 aspect ratio
    if (currentSettings.cam2_aspect_ratio) {
        const ratio2 = currentSettings.cam2_aspect_ratio.replace(':',' / ');
        cam2View.style.aspectRatio = ratio2;
    }

    applyLayout(currentSettings.camera_count);
    startImageLoop(currentSettings.check_interval);

    alert("Configuration Saved!");

    settingsModal.classList.remove('show');
    settingsModal.close();
    overlay.classList.remove('active');
    mainContent.classList.remove('blurred');  // FIXED
});

// Save AI Category Settings
document.getElementById("save-ai-cat-btn").addEventListener("click", async () => {

    currentSettings.ai_categories = {
        spaghetti: {
            enabled: document.getElementById("cat_spaghetti_enabled").checked,
            trigger: document.getElementById("cat_spaghetti_trigger").checked,
            detect_threshold: document.getElementById("cat_spaghetti_detect_threshold").value / 100,
            trigger_threshold: document.getElementById("cat_spaghetti_trigger_threshold").value / 100
        },
        blob: {
            enabled: document.getElementById("cat_blob_enabled").checked,
            trigger: document.getElementById("cat_blob_trigger").checked,
            detect_threshold: document.getElementById("cat_blob_detect_threshold").value / 100,
            trigger_threshold: document.getElementById("cat_blob_trigger_threshold").value / 100
        },
        crack: {
            enabled: document.getElementById("cat_crack_enabled").checked,
            trigger: document.getElementById("cat_crack_trigger").checked,
            detect_threshold: document.getElementById("cat_crack_detect_threshold").value / 100,
            trigger_threshold: document.getElementById("cat_crack_trigger_threshold").value / 100
        },
        warping: {
            enabled: document.getElementById("cat_warping_enabled").checked,
            trigger: document.getElementById("cat_warping_trigger").checked,
            detect_threshold: document.getElementById("cat_warping_detect_threshold").value / 100,
            trigger_threshold: document.getElementById("cat_warping_trigger_threshold").value / 100
        }
    };

    await fetch('/api/settings', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify(currentSettings)
    });

    settingsPages.classList.remove("show-ai");

    alert("AI Category Settings Saved!");
});

/********************************************************************
 * Mask drawing setup
 ********************************************************************/
setupMaskDrawing(0, cam1View);
setupMaskDrawing(1, cam2View);

/********************************************************************
 * LOG PANEL
 ********************************************************************/
let autoScrollLogs = true;

const logPanel = document.getElementById("log-panel");
const logContent = document.getElementById("log-content");
const logToggleBtn = document.getElementById("log-toggle-btn");
const logCloseBtn = document.getElementById("log-close-btn");

logToggleBtn.addEventListener("click", () => {
    logPanel.classList.toggle("hidden");
});

logCloseBtn.addEventListener("click", () => {
    logPanel.classList.add("hidden");
});

logContent.addEventListener("scroll", () => {
    const atBottom =
        logContent.scrollHeight - logContent.scrollTop <= logContent.clientHeight + 5;

    autoScrollLogs = atBottom;
});

function updateLogView(logText) {
    logContent.textContent = logText || "";
    if (autoScrollLogs) {
        logContent.scrollTop = logContent.scrollHeight;
    }
}

setInterval(async () => {
    try {
        const res = await fetch("/api/logs");
        if (!res.ok) return;
        const data = await res.json();
        updateLogView(data.logs);
    } catch (err) {}
}, 1500);

/********************************************************************
 * Load settings at startup
 ********************************************************************/
loadSettings();
