/**
 * Encryption Key Rotation - Interactive Frontend Controller
 * 5-Page Architecture with Mode Toggle (Demo vs. Real AWS), Pipeline Tracking & Honest AWS Status
 */

document.addEventListener('DOMContentLoaded', () => {
    let currentAppMode = 'demo';
    let isRotating = false;
    let activeKeyId = '450b3db5-8fbb-4693-9c95-0cc1531adb0c';
    let activeKeyVersion = 1;

    // Elements - Mode & Notifications
    const modeBtnDemo = document.getElementById('modeBtnDemo');
    const modeBtnReal = document.getElementById('modeBtnReal');
    const configNoticeBanner = document.getElementById('configNoticeBanner');
    const bannerTitle = document.getElementById('bannerTitle');
    const bannerMsg = document.getElementById('bannerMsg');
    const toastStack = document.getElementById('toastStack');

    // Real AWS Modal
    const realConfirmModal = document.getElementById('realConfirmModal');
    const modalKeyId = document.getElementById('modalKeyId');
    const modalBtnCancel = document.getElementById('modalBtnCancel');
    const modalBtnContinue = document.getElementById('modalBtnContinue');

    // Pipeline Elements
    const pipelineLiveMsg = document.getElementById('pipelineLiveMsg');
    const pstageEsp = document.getElementById('pstage-esp');
    const pstageIot = document.getElementById('pstage-iot');
    const pstageLambda = document.getElementById('pstage-lambda');
    const pstageKms = document.getElementById('pstage-kms');
    const pstageOled = document.getElementById('pstage-oled');

    const pstatEsp = document.getElementById('pstat-esp');
    const pstatIot = document.getElementById('pstat-iot');
    const pstatLambda = document.getElementById('pstat-lambda');
    const pstatKms = document.getElementById('pstat-kms');
    const pstatOled = document.getElementById('pstat-oled');

    // Control Elements
    const btnRotate = document.getElementById('btnRotate');
    const btnLabel = document.getElementById('btnLabel');
    const btnSpinner = document.getElementById('btnSpinner');

    // OLED Elements
    const oledLine1 = document.getElementById('oledLine1');
    const oledLine2 = document.getElementById('oledLine2');
    const oledLine3 = document.getElementById('oledLine3');

    // Current Key Fields
    const currentKeyId = document.getElementById('currentKeyId');
    const currentKeyStatus = document.getElementById('currentKeyStatus');
    const currentKeyVersion = document.getElementById('currentKeyVersion');
    const currentKeyLastRot = document.getElementById('currentKeyLastRot');
    const btnCopyKey = document.getElementById('btnCopyKey');
    const copyFeedbackMsg = document.getElementById('copyFeedbackMsg');

    // System Status List
    const statValEsp = document.getElementById('statValEsp');
    const statValIot = document.getElementById('statValIot');
    const statValLambda = document.getElementById('statValLambda');
    const statValKms = document.getElementById('statValKms');
    const statValOled = document.getElementById('statValOled');

    // Dashboard Elements
    const scenarioSelect = document.getElementById('scenarioSelect');
    const dashRotNum = document.getElementById('dashRotNum');
    const dashRotStatus = document.getElementById('dashRotStatus');
    const dashRotStarted = document.getElementById('dashRotStarted');
    const dashRotCompleted = document.getElementById('dashRotCompleted');
    const dashRotDuration = document.getElementById('dashRotDuration');
    const reqIdVal = document.getElementById('reqIdVal');
    const respStatusBadge = document.getElementById('respStatusBadge');
    const activityFeedList = document.getElementById('activityFeedList');

    // History & Device Elements
    const historyTableFull = document.getElementById('historyTableFull')?.querySelector('tbody');
    const btnRefreshHistory = document.getElementById('btnRefreshHistory');

    // Sidebar Navigation
    const navButtons = document.querySelectorAll('.nav-btn');
    const pageViews = document.querySelectorAll('.page-view');

    // Helper: Toast Notifications
    const showToast = (message, type = 'success') => {
        const toast = document.createElement('div');
        toast.className = 'toast-pill';
        const icon = type === 'success' 
            ? '<i class="fa-solid fa-circle-check text-forest"></i>' 
            : '<i class="fa-solid fa-circle-xmark" style="color:#EF4444;"></i>';
        toast.innerHTML = `${icon} <span>${message}</span>`;
        toastStack.appendChild(toast);
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transition = 'all 0.25s ease';
            setTimeout(() => toast.remove(), 250);
        }, 3400);
    };

    const getClockTime = () => {
        const now = new Date();
        const hrs = String(now.getHours()).padStart(2, '0');
        const mins = String(now.getMinutes()).padStart(2, '0');
        const secs = String(now.getSeconds()).padStart(2, '0');
        return `${hrs}:${mins}:${secs}`;
    };

    // Navigation Switcher (5 Pages)
    navButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetPage = btn.getAttribute('data-page');
            navButtons.forEach(b => b.classList.remove('active'));
            pageViews.forEach(v => v.classList.remove('active'));

            btn.classList.add('active');
            const activeView = document.getElementById(`page-${targetPage}`);
            if (activeView) activeView.classList.add('active');

            if (targetPage === 'history') loadHistory();
            if (targetPage === 'device') loadDeviceStatus();
        });
    });

    // Mode Toggle Logic
    modeBtnDemo.addEventListener('click', () => {
        currentAppMode = 'demo';
        modeBtnDemo.classList.add('active');
        modeBtnReal.classList.remove('active');
        configNoticeBanner.style.display = 'none';
        showToast('Switched to DEMO MODE (Safe Simulation)');
        fetchStatus();
    });

    modeBtnReal.addEventListener('click', () => {
        currentAppMode = 'real';
        modeBtnReal.classList.add('active');
        modeBtnDemo.classList.remove('active');
        fetchHealthAndWarn();
    });

    const fetchHealthAndWarn = async () => {
        try {
            const res = await fetch('/api/health');
            const data = await res.json();
            if (data.aws === 'not configured' || !data.kms_configured) {
                configNoticeBanner.style.display = 'flex';
                bannerTitle.innerText = 'AWS Not Configured';
                bannerMsg.innerText = 'KMS_KEY_ID or AWS credentials not found in .env. Live calls will fail until configured via AWS_SETUP.md.';
            } else {
                configNoticeBanner.style.display = 'none';
                showToast('REAL AWS MODE active with live AWS KMS');
            }
        } catch (e) {
            console.error(e);
        }
    };

    // Copy Key ID with visual feedback
    if (btnCopyKey) {
        btnCopyKey.addEventListener('click', () => {
            navigator.clipboard.writeText(activeKeyId).then(() => {
                copyFeedbackMsg.style.display = 'inline-flex';
                btnCopyKey.style.display = 'none';
                setTimeout(() => {
                    copyFeedbackMsg.style.display = 'none';
                    btnCopyKey.style.display = 'inline-flex';
                }, 2200);
            });
        });
    }

    // Pipeline Visual Helpers
    const resetPipelineUI = () => {
        [pstageEsp, pstageIot, pstageLambda, pstageKms, pstageOled].forEach(s => {
            s.className = 'pipe-step waiting';
        });
        pstageEsp.className = 'pipe-step ready';
        pstatEsp.innerText = 'Ready';
        pstatEsp.className = 'pipe-status-tag';

        pstatIot.innerText = 'Waiting';
        pstatIot.className = 'pipe-status-tag';

        pstatLambda.innerText = 'Waiting';
        pstatLambda.className = 'pipe-status-tag';

        pstatKms.innerText = 'Waiting';
        pstatKms.className = 'pipe-status-tag';

        pstatOled.innerText = 'Ready';
        pstatOled.className = 'pipe-status-tag';

        pipelineLiveMsg.innerText = 'Ready to rotate';
        pipelineLiveMsg.style.color = 'var(--text-secondary)';
    };

    const addActivityFeedItem = (title, subtitle, isError = false) => {
        if (!activityFeedList) return;
        const item = document.createElement('div');
        item.className = 'activity-item';
        const colorClass = isError ? 'style="color:#DC2626;"' : '';
        item.innerHTML = `
            <span class="activity-time">${getClockTime()}</span>
            <div class="activity-content">
                <strong ${colorClass}>${title}</strong>
                <small>${subtitle}</small>
            </div>
        `;
        activityFeedList.prepend(item);
    };

    // Fetch Status & Populate System Checks
    const fetchStatus = async () => {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();

            if (data.current_key) {
                activeKeyId = data.current_key.key_id;
                activeKeyVersion = data.current_key.version || 1;

                if (currentKeyId) currentKeyId.innerText = activeKeyId;
                if (currentKeyVersion) currentKeyVersion.innerText = `v${String(activeKeyVersion).padStart(2, '0')}`;
                if (currentKeyLastRot) currentKeyLastRot.innerText = data.current_key.last_rotation || 'Never';
                if (oledLine3) oledLine3.innerText = `VER: v${String(activeKeyVersion).padStart(2, '0')}`;
            }

            // Update Honest AWS Status Indicators
            if (data.aws_services) {
                updateStatusPill(statValIot, data.aws_services.iot_core.status);
                updateStatusPill(statValLambda, data.aws_services.lambda.status);
                updateStatusPill(statValKms, data.aws_services.kms.status);
            }

        } catch (e) {
            console.error('Failed to fetch status:', e);
        }
    };

    const updateStatusPill = (elem, statusStr) => {
        if (!elem) return;
        if (statusStr === 'Connected' || statusStr === 'Active' || statusStr === 'Ready') {
            elem.innerHTML = `<span class="status-dot green"></span> <span class="text-forest">${statusStr}</span>`;
        } else if (statusStr.includes('Simulation')) {
            elem.innerHTML = `<span class="status-dot blue"></span> <span class="text-blue">${statusStr}</span>`;
        } else {
            elem.innerHTML = `<span class="status-dot amber"></span> <span style="color:#D97706;">Not Configured</span>`;
        }
    };

    // Load History Table
    const loadHistory = async () => {
        if (!historyTableFull) return;
        try {
            const res = await fetch('/api/history');
            const data = await res.json();
            historyTableFull.innerHTML = '';

            if (!data.history || data.history.length === 0) {
                historyTableFull.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:1.5rem; color:#94A3B8;">No rotation history yet.</td></tr>`;
                return;
            }

            data.history.forEach(item => {
                const tr = document.createElement('tr');
                const badge = item.status === 'SUCCESS' 
                    ? '<span class="badge badge-success">SUCCESS</span>' 
                    : '<span class="badge badge-error">FAILED</span>';
                const modeBadge = item.mode === 'real'
                    ? '<span class="badge badge-neutral">Real AWS</span>'
                    : '<span class="badge badge-secondary">Demo</span>';
                const keyShort = item.key_id ? `${item.key_id.slice(0, 14)}...` : 'N/A';

                tr.innerHTML = `
                    <td class="font-mono">${item.timestamp}</td>
                    <td>${item.device_id || item.device || 'ESP32-001'}</td>
                    <td class="font-mono">${item.request_id || item.id || 'ROT-1001'}</td>
                    <td class="font-mono text-truncate" title="${item.key_id}">${keyShort}</td>
                    <td class="font-mono">v${String(item.version || 1).padStart(2, '0')}</td>
                    <td>${badge}</td>
                    <td>${modeBadge}</td>
                `;
                historyTableFull.appendChild(tr);
            });
        } catch (e) {
            console.error('History load error:', e);
        }
    };

    if (btnRefreshHistory) btnRefreshHistory.addEventListener('click', loadHistory);

    // Load Device Status Details
    const loadDeviceStatus = async () => {
        try {
            const res = await fetch('/api/device-status');
            const data = await res.json();
            if (data.device) {
                const d = data.device;
                const devPropId = document.getElementById('devPropId');
                const devPropMac = document.getElementById('devPropMac');
                if (devPropId) devPropId.innerText = d.device_id;
                if (devPropMac) devPropMac.innerText = d.mac_address;
            }
        } catch (e) {
            console.error('Device load error:', e);
        }
    };

    // Button Click Handler: Check for Real AWS Confirmation
    btnRotate.addEventListener('click', () => {
        if (isRotating) return;

        if (currentAppMode === 'real') {
            if (modalKeyId) modalKeyId.innerText = activeKeyId;
            realConfirmModal.style.display = 'flex';
        } else {
            executeRotation('demo');
        }
    });

    if (modalBtnCancel) {
        modalBtnCancel.addEventListener('click', () => {
            realConfirmModal.style.display = 'none';
        });
    }

    if (modalBtnContinue) {
        modalBtnContinue.addEventListener('click', () => {
            realConfirmModal.style.display = 'none';
            executeRotation('real');
        });
    }

    // Core Rotation Execution Routine
    const executeRotation = async (mode) => {
        isRotating = true;
        btnRotate.disabled = true;
        btnSpinner.style.display = 'inline-block';
        btnLabel.innerText = 'ROTATING KEY...';

        const startTime = Date.now();
        const startTimeClock = getClockTime();

        // Step 1: ESP32 Triggering
        pstageEsp.className = 'pipe-step active';
        pstatEsp.innerText = 'Sending...';
        pipelineLiveMsg.innerText = 'ESP32 button pressed, sending MQTT request...';
        oledLine1.innerText = 'ROTATING...';
        oledLine2.innerText = 'PLEASE WAIT';
        addActivityFeedItem('ESP32 Button Pressed', 'Request dispatched to topic: esp32/key_rotation/request');

        // Step 2: IoT Core
        await new Promise(r => setTimeout(r, 450));
        pstageEsp.className = 'pipe-step done';
        pstatEsp.innerText = '✓ Sent';

        pstageIot.className = 'pipe-step active';
        pstatIot.innerText = 'Routing...';
        pipelineLiveMsg.innerText = 'AWS IoT Core received request, evaluating Topic Rule...';
        addActivityFeedItem('AWS IoT Core', 'MQTT message received on topic esp32/key_rotation/request');

        // Step 3: Lambda
        await new Promise(r => setTimeout(r, 500));
        pstageIot.className = 'pipe-step done';
        pstatIot.innerText = '✓ Routed';

        pstageLambda.className = 'pipe-step active';
        pstatLambda.innerText = 'Executing...';
        pipelineLiveMsg.innerText = 'Lambda invoking KMS RotateKeyOnDemand API...';
        addActivityFeedItem('AWS Lambda', 'Executing ESP32-KeyRotationHandler function');

        // Step 4: KMS
        await new Promise(r => setTimeout(r, 550));
        pstageLambda.className = 'pipe-step done';
        pstatLambda.innerText = '✓ Complete';

        pstageKms.className = 'pipe-step active';
        pstatKms.innerText = 'Rotating...';
        pipelineLiveMsg.innerText = 'AWS KMS rotating key material in HSM...';
        addActivityFeedItem('AWS KMS', 'Rotating backing key material for CMK');

        const selectedScenario = scenarioSelect ? scenarioSelect.value : 'none';

        try {
            const res = await fetch('/api/rotate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ mode: mode, scenario: selectedScenario })
            });

            const data = await res.json();
            const durationSec = ((Date.now() - startTime) / 1000).toFixed(1);

            if (res.ok && data.success) {
                // Step 4 Complete
                pstageKms.className = 'pipe-step done';
                pstatKms.innerText = '✓ Rotated';

                // Step 5: OLED Screen Update
                pstageOled.className = 'pipe-step active';
                pstatOled.innerText = 'Updating...';
                await new Promise(r => setTimeout(r, 300));

                pstageOled.className = 'pipe-step done';
                pstatOled.innerText = '✓ Success';
                pipelineLiveMsg.innerText = `Key material successfully rotated to v${data.version_display || String(data.version).padStart(2, '0')}`;
                pipelineLiveMsg.style.color = 'var(--color-forest)';

                // Update UI state
                activeKeyVersion = data.version;
                if (currentKeyVersion) currentKeyVersion.innerText = `v${String(activeKeyVersion).padStart(2, '0')}`;
                if (currentKeyLastRot) currentKeyLastRot.innerText = getClockTime();

                // OLED Success Screen
                oledLine1.innerText = 'ROTATION SUCCESS';
                oledLine2.innerText = `VERSION: ${data.version_display || String(data.version).padStart(2, '0')}`;
                if (oledLine3) oledLine3.innerText = 'KEY UPDATED!';

                // Dashboard summary
                if (dashRotNum) dashRotNum.innerText = `#${data.version_display || data.version}`;
                if (dashRotStatus) { dashRotStatus.className = 'badge badge-success'; dashRotStatus.innerText = 'SUCCESS'; }
                if (dashRotStarted) dashRotStarted.innerText = startTimeClock;
                if (dashRotCompleted) dashRotCompleted.innerText = getClockTime();
                if (dashRotDuration) dashRotDuration.innerText = `${durationSec}s`;
                if (reqIdVal) reqIdVal.innerText = data.request_id || 'ROT-SUCCESS';
                if (respStatusBadge) { respStatusBadge.className = 'badge badge-success'; respStatusBadge.innerText = 'SUCCESS'; }

                addActivityFeedItem('OLED Updated', `SSD1306 display rendered version v${data.version_display || data.version}`);
                showToast(`Key rotated successfully (Version v${data.version_display || data.version})`);

            } else {
                // Failure path
                handleFailure(data, durationSec, startTimeClock);
            }

        } catch (err) {
            handleFailure({ error: 'Network / Server Error', message: err.message }, '1.2', startTimeClock);
        } finally {
            isRotating = false;
            btnRotate.disabled = false;
            btnSpinner.style.display = 'none';
            btnLabel.innerText = 'ROTATE ENCRYPTION KEY';
            setTimeout(() => {
                fetchStatus();
            }, 1000);
        }
    };

    const handleFailure = (data, durationSec, startTimeClock) => {
        pstageKms.className = 'pipe-step failed';
        pstatKms.innerText = '✕ Failed';
        pstageOled.className = 'pipe-step failed';
        pstatOled.innerText = '✕ Error';

        pipelineLiveMsg.innerText = `Rotation Failed: ${data.error || 'Check AWS configurations'}`;
        pipelineLiveMsg.style.color = 'var(--color-coral)';

        oledLine1.innerText = 'ROTATION FAILED';
        oledLine2.innerText = 'TRY AGAIN';
        if (oledLine3) oledLine3.innerText = 'ERROR';

        if (dashRotStatus) { dashRotStatus.className = 'badge badge-error'; dashRotStatus.innerText = 'FAILED'; }
        if (dashRotStarted) dashRotStarted.innerText = startTimeClock;
        if (dashRotCompleted) dashRotCompleted.innerText = getClockTime();
        if (dashRotDuration) dashRotDuration.innerText = `${durationSec}s`;
        if (respStatusBadge) { respStatusBadge.className = 'badge badge-error'; respStatusBadge.innerText = 'FAILED'; }

        addActivityFeedItem('Error Occurred', data.message || data.error || 'Execution aborted', true);
        showToast(data.message || data.error || 'Rotation failed', 'error');
    };

    // Initial Status Load
    fetchStatus();
    loadHistory();
});
