(function () {
    var POLL_MS_IDLE = 10000;
    var POLL_MS_ACTIVE = 1500;
    var timerHandle = null;
    var latestStatus = null;

    function isBlockingMaintenance(status) {
        if (!status) return false;
        if (typeof status.blocking_maintenance === 'boolean') {
            return status.blocking_maintenance;
        }
        return !!status.maintenance;
    }

    function isPipelineRunning(status) {
        return !!status && status.status === 'running';
    }

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
        var maintenanceStartedAt = toDate(latestStatus.maintenance_started_at);
        var elapsedEl = document.getElementById('pipelineElapsed');
        var etaEl = document.getElementById('pipelineEta');

        if (elapsedEl && maintenanceStartedAt) {
            var elapsedSec = Math.max(0, Math.floor((Date.now() - maintenanceStartedAt.getTime()) / 1000));
            elapsedEl.textContent = formatDuration(elapsedSec);
        } else if (elapsedEl) {
            elapsedEl.textContent = '--';
        }

        if (etaEl) {
            if (typeof latestStatus.eta_seconds === 'number' && maintenanceStartedAt) {
                var elapsed = Math.max(0, Math.floor((Date.now() - maintenanceStartedAt.getTime()) / 1000));
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

        // Bypassing maintenance overlay for documentation pages
        var isDocsPage = window.location.pathname.startsWith('/docs');
        var shouldShow = !!visible && !isDocsPage;
        
        overlay.classList.toggle('is-visible', shouldShow);
    }

    function setRunNoticeVisible(visible) {
        var notice = document.getElementById('pipelineRunNotice');
        if (!notice) return;
        notice.classList.toggle('is-visible', !!visible);
    }

    function applyStatus(status) {
        latestStatus = status || {};

        var statusText = document.getElementById('pipelineMaintenanceStatus');
        var phaseText = document.getElementById('pipelinePhase');
        var titleText = document.getElementById('pipelineMaintenanceTitle');
        var noticeStatusText = document.getElementById('pipelineRunNoticeStatus');
        var noticePhaseText = document.getElementById('pipelineRunNoticePhase');
        var blocking = isBlockingMaintenance(latestStatus);
        var running = isPipelineRunning(latestStatus);

        if (titleText) {
            titleText.textContent = blocking ? 'Data update in progress' : 'System status';
        }
        if (phaseText) {
            phaseText.textContent = latestStatus.phase || 'idle';
        }
        if (statusText) {
            statusText.textContent = latestStatus.message || 'Waiting for status';
        }
        if (noticeStatusText) {
            noticeStatusText.textContent = latestStatus.message || 'Data update in progress';
        }
        if (noticePhaseText) {
            noticePhaseText.textContent = latestStatus.phase || 'idle';
        }

        updateTimerFields();
        setOverlayVisible(blocking);
        setRunNoticeVisible(running && !blocking);
    }

    function scheduleNextTick() {
        if (timerHandle) {
            clearTimeout(timerHandle);
        }
        var active = isPipelineRunning(latestStatus);
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
