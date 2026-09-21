(function () {
    'use strict';

    var STAGES = [
        'source_check',
        'atlas',
        'timetable',
        'osm',
        'stop_matching',
        'route_matching',
        'bundle',
        'database',
        'publish'
    ];
    var LEGACY_PHASES = {
        initializing: 'source_check',
        matching: 'stop_matching',
        import: 'database'
    };
    var latestStatus = null;
    var progressTimer = null;

    function setTextIfChanged(element, value) {
        if (element && element.textContent !== value) element.textContent = value;
    }

    function setHtmlIfChanged(element, value) {
        if (element && element.innerHTML !== value) element.innerHTML = value;
    }

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

    function setStageTimestamp(element, value, meaning) {
        var date = toDate(value);
        element.textContent = date ? formatTime(value) : '—';
        if (!date) {
            element.removeAttribute('title');
            element.removeAttribute('aria-label');
            return;
        }
        var description = meaning + ' ' + date.toLocaleString();
        element.setAttribute('title', description);
        element.setAttribute('aria-label', description);
    }

    function normalizedPhase(phase) {
        if (LEGACY_PHASES[phase]) return LEGACY_PHASES[phase];
        if (STAGES.indexOf(phase) !== -1) return phase;
        if (phase === 'idle') return 'publish';
        return 'source_check';
    }

    function historyByPhase(status) {
        var result = {};
        (status.phase_history || []).forEach(function (entry) {
            if (!entry) return;
            var phase = normalizedPhase(entry.phase);
            if (STAGES.indexOf(phase) !== -1) result[phase] = entry;
        });
        return result;
    }

    function syncStageLabelTooltips() {
        document.querySelectorAll('[data-stage-label]').forEach(function (label) {
            var fullLabel = label.getAttribute('data-stage-label-full') || label.textContent.trim();
            var truncated = label.clientWidth > 0 && label.scrollWidth > label.clientWidth + 1;
            var tooltipApi = window.bootstrap && window.bootstrap.Tooltip;
            label.classList.toggle('is-truncated', truncated);

            if (truncated) {
                label.setAttribute('aria-label', fullLabel);
                label.setAttribute('tabindex', '0');
                if (!label.hasAttribute('data-stage-tooltip-bound')) {
                    label.setAttribute('title', fullLabel);
                    label.setAttribute('data-bs-title', fullLabel);
                    if (tooltipApi) {
                        tooltipApi.getOrCreateInstance(label, {trigger: 'hover focus', placement: 'top'});
                    }
                    label.setAttribute('data-stage-tooltip-bound', 'true');
                }
                return;
            }

            if (label.hasAttribute('data-stage-tooltip-bound') && tooltipApi) {
                var existing = tooltipApi.getInstance(label);
                if (existing) existing.dispose();
            }
            label.removeAttribute('data-stage-tooltip-bound');
            label.removeAttribute('data-bs-title');
            label.removeAttribute('data-bs-original-title');
            label.removeAttribute('title');
            label.removeAttribute('aria-label');
            label.removeAttribute('tabindex');
        });
    }

    function elapsedSeconds(value) {
        var started = toDate(value);
        if (!started) return 0;
        return Math.max(0, (Date.now() - started.getTime()) / 1000);
    }

    function stageDurationSeconds(entry, active, status) {
        if (entry && typeof entry.duration_seconds === 'number') {
            return Math.max(0, entry.duration_seconds);
        }
        if (active) {
            return elapsedSeconds(status.phase_started_at || status.started_at);
        }
        return null;
    }

    function setStageWeight(stageElement, seconds, useTemplateWeight) {
        if (useTemplateWeight) {
            stageElement.style.removeProperty('flex-grow');
            return;
        }
        // Waiting stages keep their CSS min-width on the right. Every elapsed
        // second increases the active stage's flex weight, so completed stages
        // occupy a progressively smaller share of the complete timeline.
        var weight = typeof seconds === 'number' ? Math.max(0.001, seconds) : 0.001;
        stageElement.style.flexGrow = weight.toFixed(3);
    }

    function progressStateParts(state) {
        var status = state.status || 'waiting';
        var label = {
            waiting: 'Waiting',
            running: 'Running',
            complete: 'Complete',
            reused: 'Reused',
            skipped: 'Skipped',
            failed: 'Failed'
        }[status] || 'Waiting';
        var details = [];
        var seconds = null;
        if (status === 'running') seconds = elapsedSeconds(state.started_at);
        else if (typeof state.duration_seconds === 'number') seconds = state.duration_seconds;
        if (seconds !== null && status !== 'reused' && status !== 'skipped') {
            details.push(formatDuration(seconds));
        }
        if (typeof state.processed === 'number' && typeof state.total === 'number' && state.total > 0) {
            details.push(state.processed + '/' + state.total);
        }
        return {label: label, details: details};
    }

    function renderProgressState(element, state) {
        if (!element) return;
        var parts = progressStateParts(state);
        setTextIfChanged(element.querySelector('.pipeline-substage__status-label'), parts.label);
        setTextIfChanged(
            element.querySelector('.pipeline-substage__status-meta'),
            parts.details.length ? ' · ' + parts.details.join(' · ') : ''
        );
    }

    function ensureStageGroup(container, phase) {
        var group = Array.prototype.find.call(container.children, function (item) {
            return item.getAttribute('data-progress-phase') === phase.id;
        });
        if (group) return group;
        group = document.createElement('section');
        group.className = 'pipeline-stage-detail';
        group.setAttribute('data-progress-phase', phase.id);
        var summary = document.createElement('div');
        summary.className = 'pipeline-stage-detail__summary';
        var label = document.createElement('span');
        label.className = 'pipeline-stage-detail__label';
        var count = document.createElement('span');
        count.className = 'pipeline-stage-detail__count';
        summary.appendChild(label);
        summary.appendChild(count);
        var list = document.createElement('ul');
        list.className = 'pipeline-substage-list';
        group.appendChild(summary);
        group.appendChild(list);
        container.appendChild(group);
        return group;
    }

    function ensureSubstage(list, spec) {
        var item = Array.prototype.find.call(list.children, function (child) {
            return child.getAttribute('data-progress-stage') === spec.id;
        });
        if (item) return item;
        item = document.createElement('li');
        item.className = 'pipeline-substage';
        item.setAttribute('data-progress-stage', spec.id);
        var marker = document.createElement('span');
        marker.className = 'pipeline-substage__marker';
        marker.setAttribute('aria-hidden', 'true');
        var body = document.createElement('span');
        body.className = 'pipeline-substage__body';
        var label = document.createElement('span');
        label.className = 'pipeline-substage__label';
        var state = document.createElement('span');
        state.className = 'pipeline-substage__status';
        var stateLabel = document.createElement('span');
        stateLabel.className = 'pipeline-substage__status-label';
        var stateMeta = document.createElement('span');
        stateMeta.className = 'pipeline-substage__status-meta';
        state.appendChild(stateLabel);
        state.appendChild(stateMeta);
        body.appendChild(label);
        body.appendChild(state);
        item.appendChild(marker);
        item.appendChild(body);
        list.appendChild(item);
        return item;
    }

    function placeChild(parent, child, index) {
        if (parent.children[index] === child) return;
        var focused = document.activeElement;
        var restoreFocus = child.contains(focused);
        parent.insertBefore(child, parent.children[index] || null);
        if (restoreFocus) focused.focus({preventScroll: true});
    }

    function renderStageDetails(status) {
        var container = document.getElementById('pipelineStageDetails');
        if (!container) return;
        var plan = Array.isArray(status.stage_plan) ? status.stage_plan : [];
        var states = status.stage_states || {};
        var roots = plan.filter(function (spec) {
            return spec && spec.parent_id === null && STAGES.indexOf(spec.id) !== -1;
        }).sort(function (a, b) { return a.order - b.order; });
        var visiblePhases = Object.create(null);
        var phaseIndex = 0;

        roots.forEach(function (phase) {
            var children = plan.filter(function (spec) {
                return spec && spec.parent_id === phase.id;
            }).sort(function (a, b) { return a.order - b.order; });
            if (!children.length) return;
            visiblePhases[phase.id] = true;
            var group = ensureStageGroup(container, phase);
            placeChild(container, group, phaseIndex++);
            var summaryLabel = group.querySelector('.pipeline-stage-detail__label');
            var summaryCount = group.querySelector('.pipeline-stage-detail__count');
            var list = group.querySelector('.pipeline-substage-list');
            setTextIfChanged(summaryLabel, phase.label);
            group.setAttribute('title', phase.description || phase.label);

            var finished = 0;
            var failed = false;
            var live = false;
            var childIds = Object.create(null);
            children.forEach(function (spec, index) {
                childIds[spec.id] = true;
                var state = states[spec.id] || {status: 'waiting'};
                var item = ensureSubstage(list, spec);
                placeChild(list, item, index);
                var statusName = state.status || 'waiting';
                item.className = 'pipeline-substage is-' + statusName;
                item.setAttribute('title', state.error || state.reason || spec.description || spec.label);
                setTextIfChanged(item.querySelector('.pipeline-substage__label'), spec.label);
                renderProgressState(item.querySelector('.pipeline-substage__status'), state);
                setTextIfChanged(item.querySelector('.pipeline-substage__marker'), statusName === 'complete' ? '✓' : statusName === 'failed' ? '!' : statusName === 'reused' ? '♻︎' : statusName === 'skipped' ? '–' : '');
                if (['complete', 'reused', 'skipped'].indexOf(statusName) !== -1) finished += 1;
                if (statusName === 'failed') failed = true;
                if (statusName === 'running') live = true;
            });
            Array.prototype.slice.call(list.querySelectorAll('[data-progress-stage]')).forEach(function (item) {
                if (!childIds[item.getAttribute('data-progress-stage')]) item.remove();
            });
            setTextIfChanged(summaryCount, failed ? 'Needs attention' : live ? 'Running' : finished + '/' + children.length + ' complete');
            group.classList.toggle('is-active', live);
            group.classList.toggle('is-failed', failed);
            group.classList.toggle('is-complete', !live && !failed && finished === children.length);
        });

        Array.prototype.slice.call(container.querySelectorAll('[data-progress-phase]')).forEach(function (group) {
            if (!visiblePhases[group.getAttribute('data-progress-phase')]) group.remove();
        });
        container.hidden = Object.keys(visiblePhases).length === 0;
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
        var outcomes = status.phase_outcomes || {};
        var completedAt = status.finished_at || status.last_pipeline_data_import_ended_at || card.getAttribute('data-last-completed');
        var successful = !running && !failed && !!completedAt;
        var warnings = status.warnings || [];
        var title = document.getElementById('analyticsPipelineTitle');
        var message = document.getElementById('analyticsPipelineMessage');
        var badge = document.getElementById('analyticsPipelineStatus');
        var elapsed = document.getElementById('analyticsPipelineElapsed');

        function setMessage(text) {
            if (!message) return;
            setTextIfChanged(message, text || '');
            message.hidden = !text;
        }

        card.classList.toggle('is-running', running);
        card.classList.toggle('is-failed', failed);

        if (running) {
            setTextIfChanged(title, 'Pipeline update in progress');
            setMessage(status.message || 'Preparing the next analytics snapshot.');
            setHtmlIfChanged(badge, '<span class="pipeline-run-card__dot"></span>Running');
            var runStarted = toDate(status.started_at);
            elapsed.textContent = runStarted ? 'Elapsed ' + formatDuration((Date.now() - runStarted.getTime()) / 1000) : 'Running';
        } else if (failed) {
            setTextIfChanged(title, status.dataset_published ? 'Dataset published; follow-up failed' : 'Latest pipeline run failed');
            setMessage(status.last_error || status.message || 'The previous analytics snapshot remains available below.');
            setHtmlIfChanged(badge, '<span class="pipeline-run-card__dot"></span>Needs attention');
            elapsed.textContent = status.finished_at ? 'Stopped ' + formatTime(status.finished_at) : 'Stopped';
        } else if (successful) {
            setTextIfChanged(title, warnings.length ? (status.dataset_published ? 'Dataset published with warnings' : 'Latest run needs attention') : 'Latest run complete');
            setMessage(warnings.join('\n'));
            setHtmlIfChanged(badge, '<span class="pipeline-run-card__dot"></span>' + (warnings.length ? 'Needs attention' : 'Complete'));
            elapsed.textContent = completedAt ? 'Completed ' + new Date(completedAt).toLocaleString() : 'Completion time unknown';
        } else {
            setTextIfChanged(title, 'Waiting for first pipeline run');
            setMessage('');
            setHtmlIfChanged(badge, '<span class="pipeline-run-card__dot"></span>Waiting');
            elapsed.textContent = 'Not started';
        }

        card.querySelectorAll('[data-pipeline-stage]').forEach(function (stageElement) {
            var phase = stageElement.getAttribute('data-pipeline-stage');
            var index = STAGES.indexOf(phase);
            var entry = history[phase];
            var outcome = outcomes[phase];
            var rootState = status.stage_states && status.stage_states[phase];
            var complete = successful || outcome === 'reused' || outcome === 'skipped' || ((running || failed) && (
                index < currentIndex || (!!entry && entry.status !== 'failed')
            ));
            var active = running && index === currentIndex;
            var stageFailed = failed && index === currentIndex;
            if (rootState) {
                complete = ['complete', 'reused', 'skipped'].indexOf(rootState.status) !== -1;
                active = running && rootState.status === 'running';
                stageFailed = rootState.status === 'failed';
                outcome = rootState.status === 'reused' || rootState.status === 'skipped' ? rootState.status : null;
                entry = rootState.finished_at ? rootState : null;
            }
            var stageSeconds = stageDurationSeconds(entry, active || stageFailed, status);
            var useTemplateWeight = !running && !failed && !history[phase];
            var progress = complete || active || stageFailed ? 1 : 0;
            var fill = stageElement.querySelector('.pipeline-timeline__fill');
            var duration = stageElement.querySelector('[data-stage-duration]');
            var timestamp = stageElement.querySelector('[data-stage-time]');
            var state = stageElement.querySelector('[data-stage-state]');

            stageElement.classList.toggle('is-complete', complete);
            stageElement.classList.toggle('is-active', active);
            stageElement.classList.toggle('is-failed', stageFailed);
            fill.style.width = (progress * 100).toFixed(1) + '%';
            setStageWeight(stageElement, stageSeconds, useTemplateWeight);
            if (state) {
                state.classList.toggle('is-complete', complete);
                state.classList.toggle('is-active', active);
                state.classList.toggle('is-failed', stageFailed);
                state.textContent = complete ? '✓' : stageFailed ? '!' : '';
            }

            if (outcome === 'reused') {
                duration.textContent = 'Reused';
                setStageTimestamp(timestamp, entry && entry.started_at, 'Reuse decided at');
            } else if (outcome === 'skipped') {
                duration.textContent = 'Skipped';
                setStageTimestamp(timestamp, entry && entry.started_at, 'Skip decided at');
            } else if (entry) {
                duration.textContent = formatDuration(entry.duration_seconds);
                setStageTimestamp(timestamp, entry.started_at, 'Started at');
            } else if (active) {
                duration.textContent = stageSeconds ? formatDuration(stageSeconds) : '0s';
                setStageTimestamp(timestamp, status.phase_started_at || status.started_at, 'Started at');
            } else if (complete) {
                duration.textContent = 'Complete';
                setStageTimestamp(timestamp, null, 'Started at');
            } else if (stageFailed) {
                duration.textContent = 'Failed';
                setStageTimestamp(timestamp, status.finished_at, 'Stopped at');
            } else {
                duration.textContent = 'Waiting';
                setStageTimestamp(timestamp, null, 'Started at');
            }
        });
        renderStageDetails(status);
        syncStageLabelTooltips();
    }

    function initSectionNavigation() {
        var nav = document.querySelector('.stats-section-nav');
        if (!nav) return;
        var links = Array.prototype.slice.call(nav.querySelectorAll('.stats-section-nav__link'));
        if (!links.length) return;
        var indicator = nav.querySelector('.stats-section-nav__indicator');
        var prefersReducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        var scrollTimer = null;
        var observerLockedUntil = 0;
        var sections = links.map(function (link) {
            return document.querySelector(link.getAttribute('href'));
        }).filter(Boolean);

        function syncSectionScrollOffset() {
            var stickyTop = parseFloat(window.getComputedStyle(nav).top) || 0;
            var offsetOwner = nav.closest('.stats-page') || document.documentElement;
            offsetOwner.style.setProperty(
                '--stats-section-scroll-offset',
                Math.ceil(stickyTop + nav.offsetHeight + 16) + 'px'
            );
        }

        function keepLinkVisible(link, smooth) {
            if (nav.scrollWidth <= nav.clientWidth) return;
            var targetLeft = link.offsetLeft - (nav.clientWidth - link.offsetWidth) / 2;
            nav.scrollTo({
                left: Math.max(0, targetLeft),
                behavior: smooth && !prefersReducedMotion ? 'smooth' : 'auto'
            });
        }

        function moveIndicator(link, animate) {
            if (!indicator || !link) return;
            if (!animate) nav.classList.remove('is-ready');
            nav.style.setProperty('--stats-nav-indicator-x', link.offsetLeft + 'px');
            nav.style.setProperty('--stats-nav-indicator-width', link.offsetWidth + 'px');
            if (!animate) {
                window.requestAnimationFrame(function () { nav.classList.add('is-ready'); });
            } else {
                nav.classList.add('is-ready');
            }
        }

        function setActiveLink(link, options) {
            options = options || {};
            links.forEach(function (candidate) {
                var active = candidate === link;
                candidate.classList.toggle('is-active', active);
                if (active) candidate.setAttribute('aria-current', 'location');
                else candidate.removeAttribute('aria-current');
            });
            moveIndicator(link, options.animate !== false);
            keepLinkVisible(link, options.animate !== false);
        }

        var hashLink = links.find(function (link) {
            return link.getAttribute('href') === window.location.hash;
        });
        var initialLink = hashLink || links.find(function (link) {
            return link.classList.contains('is-active');
        }) || links[0];
        syncSectionScrollOffset();
        setActiveLink(initialLink, {animate: false});

        links.forEach(function (link) {
            link.addEventListener('click', function (event) {
                var target = document.querySelector(link.getAttribute('href'));
                if (!target) return;
                event.preventDefault();
                if (scrollTimer) window.clearTimeout(scrollTimer);
                setActiveLink(link, {animate: true});
                observerLockedUntil = Date.now() + (prefersReducedMotion ? 0 : 700);
                window.history.replaceState(null, '', link.getAttribute('href'));
                scrollTimer = window.setTimeout(function () {
                    target.scrollIntoView({behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'start'});
                }, prefersReducedMotion ? 0 : 80);
            });
        });

        window.addEventListener('resize', function () {
            var active = nav.querySelector('.stats-section-nav__link.is-active');
            syncSectionScrollOffset();
            moveIndicator(active, false);
        });

        if (!('IntersectionObserver' in window)) return;
        var observer = new IntersectionObserver(function (entries) {
            if (Date.now() < observerLockedUntil) return;
            var visible = entries.filter(function (entry) { return entry.isIntersecting; })
                .sort(function (a, b) { return a.boundingClientRect.top - b.boundingClientRect.top; });
            if (!visible.length) return;
            var activeId = '#' + visible[0].target.id;
            var activeLink = links.find(function (link) {
                return link.getAttribute('href') === activeId;
            });
            if (activeLink && !activeLink.classList.contains('is-active')) setActiveLink(activeLink, {animate: true});
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
        window.addEventListener('resize', syncStageLabelTooltips);
        window.addEventListener('pagehide', function () {
            if (progressTimer) window.clearInterval(progressTimer);
            window.removeEventListener('resize', syncStageLabelTooltips);
        }, {once: true});
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();
})();
