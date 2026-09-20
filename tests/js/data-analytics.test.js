const fs = require('fs');
const path = require('path');

function stageMarkup(phase) {
  return `
    <div data-pipeline-stage="${phase}">
      <span class="pipeline-timeline__fill"></span>
      <strong data-stage-duration></strong>
      <span data-stage-time></span>
    </div>`;
}

describe('analytics pipeline timeline', () => {
  beforeAll(() => {
    jest.useFakeTimers();
    document.body.innerHTML = `
      <section id="pipelineRunCard" data-last-completed="2026-09-20T10:00:00Z">
        <h2 id="analyticsPipelineTitle"></h2>
        <p id="analyticsPipelineMessage"></p>
        <span id="analyticsPipelineStatus"></span>
        <span id="analyticsPipelineElapsed"></span>
        ${stageMarkup('initializing')}
        ${stageMarkup('matching')}
        ${stageMarkup('import')}
        ${stageMarkup('publish')}
      </section>`;

    const scriptPath = path.join(__dirname, '../../static/js/pages/data-analytics.js');
    window.eval(fs.readFileSync(scriptPath, 'utf8'));
    document.dispatchEvent(new Event('DOMContentLoaded'));
  });

  afterAll(() => {
    window.dispatchEvent(new Event('pagehide'));
    jest.useRealTimers();
  });

  test('grows the active stage while keeping later stages waiting', () => {
    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {
        status: 'running',
        phase: 'matching',
        message: 'Matching source records',
        started_at: new Date(Date.now() - 120000).toISOString(),
        phase_started_at: new Date(Date.now() - 60000).toISOString(),
        phase_history: [{
          phase: 'initializing',
          started_at: new Date(Date.now() - 125000).toISOString(),
          duration_seconds: 5
        }]
      }
    }));

    const card = document.getElementById('pipelineRunCard');
    const initializing = card.querySelector('[data-pipeline-stage="initializing"]');
    const matching = card.querySelector('[data-pipeline-stage="matching"]');
    const importing = card.querySelector('[data-pipeline-stage="import"]');

    expect(card.classList.contains('is-running')).toBe(true);
    expect(document.getElementById('analyticsPipelineTitle').textContent).toBe('Pipeline update in progress');
    expect(initializing.classList.contains('is-complete')).toBe(true);
    expect(initializing.querySelector('.pipeline-timeline__fill').style.width).toBe('100.0%');
    expect(matching.classList.contains('is-active')).toBe(true);
    expect(parseFloat(matching.querySelector('.pipeline-timeline__fill').style.width)).toBeGreaterThan(0);
    expect(importing.querySelector('[data-stage-duration]').textContent).toBe('Waiting');
  });

  test('leaves every fixed-width stage complete after a successful run', () => {
    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {
        status: 'idle',
        phase: 'idle',
        finished_at: '2026-09-20T11:00:00Z',
        phase_history: []
      }
    }));

    const stages = Array.from(document.querySelectorAll('[data-pipeline-stage]'));
    expect(stages.every(stage => stage.classList.contains('is-complete'))).toBe(true);
    expect(stages.every(stage => stage.querySelector('.pipeline-timeline__fill').style.width === '100.0%')).toBe(true);
    expect(document.getElementById('analyticsPipelineStatus').textContent).toContain('Complete');
    expect(document.getElementById('analyticsPipelineMessage').hidden).toBe(true);
  });

  test('marks the interrupted stage without presenting it as complete', () => {
    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {
        status: 'failed',
        phase: 'failed',
        failed_phase: 'matching',
        last_error: 'Source unavailable',
        finished_at: '2026-09-20T11:00:00Z',
        phase_history: [{
          phase: 'matching',
          started_at: '2026-09-20T10:50:00Z',
          duration_seconds: 600,
          status: 'failed'
        }]
      }
    }));

    const matching = document.querySelector('[data-pipeline-stage="matching"]');
    expect(document.getElementById('pipelineRunCard').classList.contains('is-failed')).toBe(true);
    expect(matching.classList.contains('is-failed')).toBe(true);
    expect(matching.classList.contains('is-complete')).toBe(false);
    expect(parseFloat(matching.querySelector('.pipeline-timeline__fill').style.width)).toBeGreaterThan(0);
  });
});
