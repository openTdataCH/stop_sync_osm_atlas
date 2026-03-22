(function () {
    var POLL_MS_IDLE = 10000;
    var POLL_MS_ACTIVE = 1500;
    var timerHandle = null;
    var latestStatus = null;

    function toDate(value) {
        if (!value) return null;
        var d = new Date(value);
        return Number.isNaN(d.getTime()) ? null : d;
    }

    function formatDuration(totalSeconds) {
        if (typeof totalSeconds !== 'number' || totalSeconds < 0) return '--';
        var s = Math.floor(totalSeconds % 60);
        var m = Math.floor((totalSeconds / 60) % 60);
        var h = Math.floor(totalSeconds / 3600);
        if (h > 0) return h + 'h ' + m + 'm';
        return m + 'm ' + s + 's';
    }

    function updateTimerFields() {
        if (!latestStatus) return;
        var startedAt = toDate(latestStatus.started_at);
        var elapsedEl = document.getElementById('pipelineElapsed');
        var etaEl = document.getElementById('pipelineEta');

        if (elapsedEl && startedAt) {
            var elapsedSec = Math.max(0, Math.floor((Date.now() - startedAt.getTime()) / 1000));
            elapsedEl.textContent = formatDuration(elapsedSec);
        }

        if (etaEl) {
            if (typeof latestStatus.eta_seconds === 'number' && startedAt) {
                var elapsed = Math.max(0, Math.floor((Date.now() - startedAt.getTime()) / 1000));
                var remaining = Math.max(0, latestStatus.eta_seconds - elapsed);
                etaEl.textContent = formatDuration(remaining);
            } else {
                etaEl.textContent = '--';
            }
        }
    }

    function setOverlayVisible(visible) {
        var overlay = document.getElementById('pipelineMaintenanceOverlay');
        if (!overlay) return;
        overlay.classList.toggle('is-visible', !!visible);
    }

    function applyStatus(status) {
        latestStatus = status || {};

        var statusText = document.getElementById('pipelineMaintenanceStatus');
        var phaseText = document.getElementById('pipelinePhase');
        var titleText = document.getElementById('pipelineMaintenanceTitle');

        if (titleText) {
            titleText.textContent = latestStatus.maintenance ? 'Data update in progress' : 'System status';
        }
        if (phaseText) {
            phaseText.textContent = latestStatus.phase || 'idle';
        }
        if (statusText) {
            statusText.textContent = latestStatus.message || 'Waiting for status';
        }

        updateTimerFields();
        setOverlayVisible(!!latestStatus.maintenance);
    }

    function scheduleNextTick() {
        if (timerHandle) {
            clearTimeout(timerHandle);
        }
        var active = latestStatus && latestStatus.maintenance;
        timerHandle = setTimeout(fetchStatus, active ? POLL_MS_ACTIVE : POLL_MS_IDLE);
    }

    function fetchStatus() {
        $.ajax({
            url: '/api/system/pipeline_status',
            method: 'GET',
            cache: false,
            timeout: 5000
        }).done(function (status) {
            applyStatus(status);
        }).always(function () {
            scheduleNextTick();
        });
    }

    function start() {
        setInterval(updateTimerFields, 1000);
        fetchStatus();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
