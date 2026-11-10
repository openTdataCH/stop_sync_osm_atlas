/**
 * The export progress overlay (templates/components/export_overlay.html), used
 * by the Data page's exports and the documentation PDF. A task is started with
 * a POST, polled until it is complete, and its file is then downloaded.
 */
(function (global) {
    'use strict';

    // Keep polling comfortably under the 240/min report progress limiter.
    var PROGRESS_POLL_INTERVAL_MS = 1500;
    var TARGET_PROGRESS_DURATION_MS = 20000;
    var MAX_ACTIVE_PROGRESS_PERCENT = 95;
    var PROGRESS_ANIMATION_INTERVAL_MS = 120;
    var START_TIMEOUT_MS = 10000;
    var POLL_TIMEOUT_MS = 8000;
    var CANCEL_TIMEOUT_MS = 5000;

    var task = null;            // { id, checkUrl, downloadUrl, cancelUrl, showCounters }
    var status = 'starting';
    var pollTimer = null;
    var animationTimer = null;
    var animationStartedAt = null;
    var progressValue = 0;

    function byId(id) {
        return document.getElementById(id);
    }

    function setText(id, text) {
        var element = byId(id);
        if (element) element.textContent = text;
    }

    function setShown(id, shown) {
        var element = byId(id);
        if (element) element.style.display = shown ? '' : 'none';
    }

    function setBarStriped(striped) {
        var bar = byId('reportProgressBar');
        if (!bar) return;
        bar.classList.toggle('progress-bar-striped', striped);
        bar.classList.toggle('progress-bar-animated', striped);
    }

    function setProgressBarValue(value) {
        progressValue = Math.max(0, Math.min(100, Math.round(value || 0)));
        var bar = byId('reportProgressBar');
        if (!bar) return;
        bar.style.width = progressValue + '%';
        bar.setAttribute('aria-valuenow', progressValue);
    }

    // fetchJson with a time limit; the request is aborted when it runs out.
    function fetchJsonWithin(ms, url, options) {
        var controller = new AbortController();
        var timer = setTimeout(function () { controller.abort(); }, ms);
        return SharedUtils.fetchJson(url, null, Object.assign({ signal: controller.signal }, options))
            .finally(function () { clearTimeout(timer); });
    }

    // The bar eases towards 95 % over about 20 s while the server works, as
    // the progress the server reports is too coarse to show.
    function timedProgressPercent() {
        if (!animationStartedAt) return 0;
        var elapsed = Math.min((Date.now() - animationStartedAt) / TARGET_PROGRESS_DURATION_MS, 1);
        return MAX_ACTIVE_PROGRESS_PERCENT * (1 - Math.pow(1 - elapsed, 3));
    }

    function activeProgressText(percent) {
        if (status === 'starting' && percent < 10) return 'Starting...';
        return 'Generating file... ' + percent + '%';
    }

    function renderTimedProgress() {
        if (status === 'completed' || status === 'error') return;
        setProgressBarValue(Math.max(progressValue, timedProgressPercent()));
        setText('progressText', activeProgressText(progressValue));
    }

    function startProgressAnimation() {
        if (!animationStartedAt) animationStartedAt = Date.now();
        stopProgressAnimation();
        setBarStriped(true);
        animationTimer = setInterval(renderTimedProgress, PROGRESS_ANIMATION_INTERVAL_MS);
        renderTimedProgress();
    }

    function stopProgressAnimation() {
        if (animationTimer) {
            clearInterval(animationTimer);
            animationTimer = null;
        }
    }

    function stopProgressPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    function updateProgressCounters(processed, total) {
        setText('entriesProcessed', processed.toLocaleString());
        setText('totalEntries', total.toLocaleString());
        setShown('progressCounters', !!(task && task.showCounters && total > 0));
    }

    function hideOverlay() {
        setShown('reportLoadingOverlay', false);
    }

    function showError(message) {
        if (typeof message !== 'string') {
            message = 'An error occurred during report generation.';
        }
        stopProgressAnimation();
        setShown('progressControls', false);
        setText('errorMessage', message);
        setShown('errorSection', true);
    }

    /** Resets the overlay and shows it, titled title. */
    function open(title) {
        setText('overlayTitle', title || 'Generating Report');
        stopProgressAnimation();
        stopProgressPolling();
        animationStartedAt = null;
        status = 'starting';
        task = null;
        setProgressBarValue(0);
        setBarStriped(false);
        setText('progressText', 'Starting...');
        setText('entriesProcessed', '0');
        setText('totalEntries', '0');
        setShown('progressCounters', false);
        setShown('downloadSection', false);
        setShown('errorSection', false);
        setShown('progressControls', true);
        setShown('reportLoadingOverlay', true);
    }

    function updateProgress(progress) {
        if (!progress) return;
        status = progress.status || 'processing';
        updateProgressCounters(progress.processed || 0, progress.total || 0);

        if (status === 'starting') {
            setText('progressText', 'Starting...');
            if (!animationTimer) startProgressAnimation();
        } else if (status === 'processing' || status === 'finalizing') {
            if (!animationTimer) startProgressAnimation();
            renderTimedProgress();
        } else if (status === 'completed') {
            stopProgressAnimation();
            setText('progressText', 'Complete!');
            setProgressBarValue(100);
            setBarStriped(false);
            stopProgressPolling();
            showDownloadSection();
        } else if (status === 'error') {
            stopProgressAnimation();
            stopProgressPolling();
            showError(progress.error || 'Unknown error occurred');
        }
    }

    function startProgressPolling() {
        stopProgressPolling();
        pollTimer = setInterval(function () {
            if (!task || !task.id) return;
            var polled = task;
            fetchJsonWithin(POLL_TIMEOUT_MS, polled.checkUrl + polled.id).then(function (progress) {
                if (task === polled) updateProgress(progress);
            }, function (error) {
                // Keep polling unless the task was cancelled.
                if (task !== polled) return;
                console.log(error.status === 429
                    ? 'Progress polling rate-limited; retrying...'
                    : 'Progress polling error, continuing...');
            });
        }, PROGRESS_POLL_INTERVAL_MS);
    }

    function downloadFilename(response) {
        var disposition = response.headers.get('content-disposition') || '';
        var utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
        if (utf8Match && utf8Match[1]) return decodeURIComponent(utf8Match[1]);
        var asciiMatch = disposition.match(/filename="?([^";]+)"?/i);
        return asciiMatch && asciiMatch[1] ? asciiMatch[1] : null;
    }

    function triggerBrowserDownload(blob, filename) {
        var objectUrl = global.URL.createObjectURL(blob);
        var link = document.createElement('a');
        link.href = objectUrl;
        link.download = filename || 'download';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(function () { global.URL.revokeObjectURL(objectUrl); }, 1000);
    }

    function downloadError(response, bodyText) {
        var contentType = response.headers.get('content-type') || '';
        if (contentType.indexOf('application/json') !== -1) {
            try {
                var payload = JSON.parse(bodyText);
                if (payload && (payload.error || payload.message)) return payload.error || payload.message;
            } catch (e) {
                // Fall back to plain text handling below.
            }
        }
        if (bodyText) return bodyText;
        return response.status ? 'Download failed (' + response.status + ').' : 'Download failed.';
    }

    function downloadCompletedTask(downloadUrl) {
        setText('progressText', 'Preparing download...');
        fetch(downloadUrl, { method: 'GET', credentials: 'same-origin' })
            .then(function (response) {
                if (!response.ok) {
                    return response.text().then(function (bodyText) {
                        throw new Error(downloadError(response, bodyText));
                    });
                }
                var filename = downloadFilename(response);
                return response.blob().then(function (blob) {
                    return { blob: blob, filename: filename };
                });
            })
            .then(function (result) {
                triggerBrowserDownload(result.blob, result.filename);
                setTimeout(hideOverlay, 500);
            })
            .catch(function (error) {
                showError(error && error.message ? error.message : 'Download failed.');
            });
    }

    function showDownloadSection() {
        setShown('progressControls', false);
        setShown('downloadSection', true);
        var finished = task;
        if (finished && finished.id) {
            // Download the file automatically.
            setTimeout(function () {
                downloadCompletedTask(finished.downloadUrl + finished.id);
            }, 500);
        }
    }

    /**
     * Starts a task. options: generateUrl, params (the POST body), checkUrl,
     * downloadUrl and cancelUrl (each followed by the task id), and
     * showCounters, to show the entries processed.
     */
    function start(options) {
        var config = options || {};
        if (!config.generateUrl) {
            showError('Task endpoint is not configured.');
            return;
        }
        var current = {
            id: null,
            checkUrl: config.checkUrl || '/api/report_progress/',
            downloadUrl: config.downloadUrl || '/api/download_report/',
            cancelUrl: config.cancelUrl || '/api/cancel_report/',
            showCounters: !!config.showCounters
        };
        task = current;
        var params = config.params && typeof config.params === 'object' && !Array.isArray(config.params) ? config.params : {};

        fetchJsonWithin(START_TIMEOUT_MS, config.generateUrl, { method: 'POST', body: params }).then(function (response) {
            if (task !== current) return;
            if (response.task_id) {
                current.id = response.task_id;
                status = 'starting';
                startProgressAnimation();
                startProgressPolling();
            } else {
                showError('Failed to start task');
            }
        }, function (error) {
            if (task !== current) return;
            var message = error.status === 429
                ? 'Rate limit exceeded. Please wait a while before requesting another report.'
                : SharedUtils.buildErrorMessage(error, 'Unknown error');
            showError('Error starting task: ' + message);
        });
    }

    /** Stops the task on the server and hides the overlay. */
    function cancel() {
        var cancelled = task;
        task = null;
        if (cancelled && cancelled.id) {
            fetchJsonWithin(CANCEL_TIMEOUT_MS, cancelled.cancelUrl + cancelled.id, { method: 'POST', body: {} })
                .catch(function () { /* the overlay is closed either way */ });
        }
        stopProgressPolling();
        stopProgressAnimation();
        hideOverlay();
    }

    document.addEventListener('click', function (event) {
        if (event.target.closest && event.target.closest('#cancelReportBtn')) cancel();
    });

    global.ExportProgress = {
        open: open,
        start: start,
        cancel: cancel,
        updateProgress: updateProgress
    };
})(window);
