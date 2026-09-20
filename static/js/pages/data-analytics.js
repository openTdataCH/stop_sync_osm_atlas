(function () {
    'use strict';

    var STAGES = ['initializing', 'matching', 'import', 'publish'];
    var EXPECTED_SECONDS = {
        initializing: 45,
        matching: 3600,
        import: 180,
        publish: 45
    };
    var latestStatus = null;
    var progressTimer = null;

    function toDate(value) {
        if (!value) return null;
        var parsed = new Date(value);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    function formatDuration(seconds) {
        if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return '—';
        var rounded = Math.max(0, Math.round(seconds));
        var hours = Math.floor(rounded / 3600);
        var minutes = Math.floor((rounded % 3600) / 60);
        var remainder = rounded % 60;
        if (hours) return hours + 'h ' + minutes + 'm';
        if (minutes) return minutes + 'm ' + remainder + 's';
        return remainder + 's';
    }

    function formatTime(value) {
        var date = toDate(value);
        if (!date) return '—';
        return date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'});
    }

    function normalizedPhase(phase) {
        if (STAGES.indexOf(phase) !== -1) return phase;
        if (phase === 'idle') return 'publish';
        return 'initializing';
    }

    function historyByPhase(status) {
        var result = {};
        (status.phase_history || []).forEach(function (entry) {
            if (entry && STAGES.indexOf(entry.phase) !== -1) result[entry.phase] = entry;
        });
        return result;
    }

    function currentStageProgress(status, phase) {
        if (typeof status.processed === 'number' && typeof status.total === 'number' && status.total > 0) {
            return Math.min(0.98, Math.max(0.04, status.processed / status.total));
        }
        var started = toDate(status.phase_started_at || status.started_at);
        if (!started) return 0.08;
        var elapsed = Math.max(0, (Date.now() - started.getTime()) / 1000);
        var expected = EXPECTED_SECONDS[phase] || 120;
        return Math.min(0.96, Math.max(0.04, elapsed / expected));
    }

    function renderPipeline(status) {
        var card = document.getElementById('pipelineRunCard');
        if (!card || !status) return;

        latestStatus = status;
        var running = status.status === 'running';
        var failed = status.status === 'failed';
        var currentPhase = normalizedPhase(failed ? status.failed_phase : status.phase);
        var currentIndex = STAGES.indexOf(currentPhase);
        var history = historyByPhase(status);
        var title = document.getElementById('analyticsPipelineTitle');
        var message = document.getElementById('analyticsPipelineMessage');
        var badge = document.getElementById('analyticsPipelineStatus');
        var elapsed = document.getElementById('analyticsPipelineElapsed');

        function setMessage(text) {
            if (!message) return;
            message.textContent = text || '';
            message.hidden = !text;
        }

        card.classList.toggle('is-running', running);
        card.classList.toggle('is-failed', failed);

        if (running) {
            title.textContent = 'Pipeline update in progress';
            setMessage(status.message || 'Preparing the next analytics snapshot.');
            badge.innerHTML = '<span class="pipeline-run-card__dot"></span>Running';
            var runStarted = toDate(status.started_at);
            elapsed.textContent = runStarted ? 'Elapsed ' + formatDuration((Date.now() - runStarted.getTime()) / 1000) : 'Running';
        } else if (failed) {
            title.textContent = 'Latest pipeline run failed';
            setMessage(status.last_error || status.message || 'The previous analytics snapshot remains available below.');
            badge.innerHTML = '<span class="pipeline-run-card__dot"></span>Needs attention';
            elapsed.textContent = status.finished_at ? 'Stopped ' + formatTime(status.finished_at) : 'Stopped';
        } else {
            title.textContent = 'Latest run complete';
            setMessage('');
            badge.innerHTML = '<span class="pipeline-run-card__dot"></span>Complete';
            var completedAt = status.finished_at || status.last_pipeline_data_import_ended_at || card.getAttribute('data-last-completed');
            elapsed.textContent = completedAt ? 'Completed ' + new Date(completedAt).toLocaleString() : 'Completion time unknown';
        }

        card.querySelectorAll('[data-pipeline-stage]').forEach(function (stageElement) {
            var phase = stageElement.getAttribute('data-pipeline-stage');
            var index = STAGES.indexOf(phase);
            var entry = history[phase];
            var complete = !running && !failed ? true : index < currentIndex || (!!entry && entry.status !== 'failed');
            var active = running && index === currentIndex;
            var stageFailed = failed && index === currentIndex;
            var failedProgress = entry && typeof entry.duration_seconds === 'number'
                ? Math.min(0.96, Math.max(0.04, entry.duration_seconds / (EXPECTED_SECONDS[phase] || 120)))
                : 0.08;
            var progress = complete ? 1 : active ? currentStageProgress(status, phase) : stageFailed ? failedProgress : 0;
            var fill = stageElement.querySelector('.pipeline-timeline__fill');
            var duration = stageElement.querySelector('[data-stage-duration]');
            var timestamp = stageElement.querySelector('[data-stage-time]');

            stageElement.classList.toggle('is-complete', complete);
            stageElement.classList.toggle('is-active', active);
            stageElement.classList.toggle('is-failed', stageFailed);
            fill.style.width = (progress * 100).toFixed(1) + '%';

            if (entry) {
                duration.textContent = formatDuration(entry.duration_seconds);
                timestamp.textContent = formatTime(entry.started_at);
            } else if (active) {
                var phaseStarted = toDate(status.phase_started_at || status.started_at);
                duration.textContent = phaseStarted ? formatDuration((Date.now() - phaseStarted.getTime()) / 1000) : 'Running';
                timestamp.textContent = formatTime(status.phase_started_at || status.started_at);
            } else if (complete) {
                duration.textContent = 'Complete';
                timestamp.textContent = '—';
            } else if (stageFailed) {
                duration.textContent = 'Failed';
                timestamp.textContent = formatTime(status.finished_at);
            } else {
                duration.textContent = 'Waiting';
                timestamp.textContent = '—';
            }
        });
    }

    function initSectionNavigation() {
        var links = Array.prototype.slice.call(document.querySelectorAll('.stats-section-nav__link'));
        if (!links.length) return;
        var sections = links.map(function (link) {
            return document.querySelector(link.getAttribute('href'));
        }).filter(Boolean);

        links.forEach(function (link) {
            link.addEventListener('click', function (event) {
                var target = document.querySelector(link.getAttribute('href'));
                if (!target) return;
                event.preventDefault();
                target.scrollIntoView({behavior: 'smooth', block: 'start'});
                window.history.replaceState(null, '', link.getAttribute('href'));
            });
        });

        if (!('IntersectionObserver' in window)) return;
        var observer = new IntersectionObserver(function (entries) {
            var visible = entries.filter(function (entry) { return entry.isIntersecting; })
                .sort(function (a, b) { return a.boundingClientRect.top - b.boundingClientRect.top; });
            if (!visible.length) return;
            var activeId = '#' + visible[0].target.id;
            links.forEach(function (link) {
                var active = link.getAttribute('href') === activeId;
                link.classList.toggle('is-active', active);
                if (active) link.setAttribute('aria-current', 'location');
                else link.removeAttribute('aria-current');
            });
        }, {rootMargin: '-20% 0px -70% 0px', threshold: 0});
        sections.forEach(function (section) { observer.observe(section); });
    }

    function start() {
        initSectionNavigation();
        document.addEventListener('pipeline-status:update', function (event) {
            renderPipeline(event.detail || {});
        });
        if (window.latestPipelineStatus) renderPipeline(window.latestPipelineStatus);
        progressTimer = window.setInterval(function () {
            if (latestStatus && latestStatus.status === 'running') renderPipeline(latestStatus);
        }, 1000);
        window.addEventListener('pagehide', function () {
            if (progressTimer) window.clearInterval(progressTimer);
        }, {once: true});
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
