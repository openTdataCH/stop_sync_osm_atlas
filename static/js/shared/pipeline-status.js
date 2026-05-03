(function () {
    var POLL_MS_IDLE = 10000;
    var POLL_MS_ACTIVE = 1500;
    var timerHandle = null;
    var latestStatus = null;

    function getDataUpdatedElement() {
        return document.getElementById('navbarDataUpdated');
    }

    function getDataUpdatedTextElement() {
        return document.getElementById('navbarDataUpdatedText');
    }

    function getNextRunInfoElement() {
        return document.getElementById('navbarNextRunInfo');
    }

    function isBlockingMaintenance(status) {
        if (!status) return false;
        return !!status.blocking_maintenance;
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

    function formatNextRunTime(value) {
        if (!value) return '';
        return value.toLocaleString([], {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    }

    function formatLabelTimestamp(value) {
        if (!value || value.length < 16) {
            return '';
        }
        return value.slice(0, 10) + ' ' + value.slice(11, 16);
    }

    function getNextRunAtValue(element) {
        if (!element) return null;
        if (latestStatus && latestStatus.next_run_at) {
            return latestStatus.next_run_at;
        }
        return element.getAttribute('data-pipeline-next-run-at');
    }

    function buildNextRunTooltipText(element) {
        if (!element) return '';

        var nextRunAt = toDate(getNextRunAtValue(element));
        if (!nextRunAt) {
            return '';
        }

        return 'Next pipeline run: ' + formatNextRunTime(nextRunAt);
    }

    function syncBootstrapTooltip(element, tooltipText) {
        var tooltipApi = window.bootstrap && window.bootstrap.Tooltip;
        if (!tooltipApi || !element) {
            return;
        }

        var existing = tooltipApi.getInstance(element);
        if (!tooltipText) {
            if (existing) {
                existing.dispose();
            }
            return;
        }

        if (existing) {
            existing.dispose();
        }

        tooltipApi.getOrCreateInstance(element, {
            trigger: 'hover focus',
            placement: 'bottom'
        });
    }

    function syncNextRunInfo() {
        var dataUpdatedElement = getDataUpdatedElement();
        var infoElement = getNextRunInfoElement();
        if (!dataUpdatedElement || !infoElement) {
            return;
        }

        var tooltipText = buildNextRunTooltipText(dataUpdatedElement);
        if (!tooltipText) {
            infoElement.hidden = true;
            infoElement.removeAttribute('title');
            infoElement.removeAttribute('data-bs-original-title');
            infoElement.removeAttribute('data-bs-title');
            syncBootstrapTooltip(infoElement, '');
            return;
        }

        infoElement.hidden = false;
        infoElement.setAttribute('data-bs-title', tooltipText);
        infoElement.setAttribute('title', tooltipText);
        syncBootstrapTooltip(infoElement, tooltipText);
    }

    function syncNavbarStatusLabel() {
        var element = getDataUpdatedElement();
        var textElement = getDataUpdatedTextElement();
        if (!element || !textElement) {
            return;
        }

        var blocking = isBlockingMaintenance(latestStatus);
        var running = isPipelineRunning(latestStatus);

        if (running) {
            if (blocking) {
                textElement.textContent = element.getAttribute('data-blocking-label') || 'Pipeline running';
            } else {
                textElement.textContent = element.getAttribute('data-running-label') || 'Pipeline running in the background';
            }
            return;
        }

        textElement.textContent = element.getAttribute('data-default-label') || textElement.textContent;
    }

    function syncNavbarDataUpdatedValue() {
        var element = getDataUpdatedElement();
        if (!element || !latestStatus || !latestStatus.data_updated_at) {
            return;
        }

        var formatted = formatLabelTimestamp(latestStatus.data_updated_at);
        if (!formatted) {
            return;
        }

        element.setAttribute('data-data-updated-at', latestStatus.data_updated_at);
        element.setAttribute('data-default-label', 'Data updated: ' + formatted);
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
            if (blocking) {
                var message = latestStatus.message || 'Core data is being refreshed.';
                var docsLink = document.getElementById('pipelineDocsLink');
                var docsUrl = docsLink ? docsLink.getAttribute('href') : '/docs';
                
                statusText.textContent = message + ' Use this time to ';
                var a = document.createElement('a');
                a.href = docsUrl;
                a.id = 'pipelineDocsLink';
                a.className = 'fw-bold';
                a.textContent = 'read the documentation';
                statusText.appendChild(a);
                statusText.appendChild(document.createTextNode('.'));
            } else {
                statusText.textContent = latestStatus.message || 'Waiting for status';
            }
        }
        if (noticeStatusText) {
            noticeStatusText.textContent = latestStatus.message || 'Data update in progress';
        }
        if (noticePhaseText) {
            noticePhaseText.textContent = latestStatus.phase || 'idle';
        }

        var dataUpdatedEl = getDataUpdatedElement();
        if (dataUpdatedEl) {
            if (Object.prototype.hasOwnProperty.call(latestStatus, 'next_run_at')) {
                dataUpdatedEl.setAttribute('data-pipeline-next-run-at', latestStatus.next_run_at || '');
            }
            syncNavbarDataUpdatedValue();
        }
        syncNavbarStatusLabel();
        syncNextRunInfo();

        updateTimerFields();
        setOverlayVisible(blocking);
        // Keep background phases silent in UI; only blocking maintenance should interrupt users.
        setRunNoticeVisible(false);
    }

    function scheduleNextTick() {
        if (timerHandle) {
            clearTimeout(timerHandle);
        }
        var active = isPipelineRunning(latestStatus);
        timerHandle = setTimeout(fetchStatus, active ? POLL_MS_ACTIVE : POLL_MS_IDLE);
    }

    function fetchStatus() {
        if (!window.$ || typeof window.$.ajax !== 'function') {
            scheduleNextTick();
            return;
        }

        window.$.ajax({
            url: '/api/system/pipeline_status',
            method: 'GET',
            dataType: 'json',
            cache: false,
            timeout: 5000,
            success: function (status) {
                applyStatus(status);
            },
            complete: function () {
                scheduleNextTick();
            }
        });
    }

    function start() {
        syncNavbarStatusLabel();
        syncNextRunInfo();
        setInterval(updateTimerFields, 1000);
        fetchStatus();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
