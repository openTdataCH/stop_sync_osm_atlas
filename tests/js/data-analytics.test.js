const fs = require('fs');
const path = require('path');

function stageMarkup(phase) {
  return `
    <div data-pipeline-stage="${phase}">
      <span data-stage-label data-stage-label-full="${phase}">${phase}</span>
      <span class="pipeline-timeline__fill"></span>
      <strong data-stage-duration></strong>
      <span data-stage-state></span>
      <span data-stage-time></span>
    </div>`;
}

describe('analytics pipeline timeline', () => {
  const stages = [
    'source_check', 'atlas', 'timetable', 'osm', 'stop_matching',
    'route_matching', 'bundle', 'database', 'publish'
  ];

  beforeAll(() => {
    jest.useFakeTimers();
    document.body.innerHTML = `
      <nav class="stats-section-nav">
        <span class="stats-section-nav__indicator"></span>
        <a class="stats-section-nav__link is-active" href="#stops-matching">Matching</a>
        <a class="stats-section-nav__link" href="#routes">Routes</a>
      </nav>
      <h2 id="stops-matching">Stops matching</h2>
      <h2 id="routes">Routes</h2>
      <section id="pipelineRunCard" data-last-completed="2026-09-20T10:00:00Z">
        <h2 id="analyticsPipelineTitle"></h2>
        <p id="analyticsPipelineMessage"></p>
        <span id="analyticsPipelineStatus"></span>
        <span id="analyticsPipelineElapsed"></span>
        ${stages.map(stageMarkup).join('')}
        <div id="pipelineStageDetails"></div>
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
        phase: 'stop_matching',
        message: 'Stop matching',
        started_at: new Date(Date.now() - 120000).toISOString(),
        phase_started_at: new Date(Date.now() - 60000).toISOString(),
        phase_history: [{
          phase: 'source_check',
          started_at: new Date(Date.now() - 125000).toISOString(),
          duration_seconds: 5
        }]
      }
    }));

    const card = document.getElementById('pipelineRunCard');
    const initializing = card.querySelector('[data-pipeline-stage="source_check"]');
    const matching = card.querySelector('[data-pipeline-stage="stop_matching"]');
    const importing = card.querySelector('[data-pipeline-stage="database"]');

    expect(card.classList.contains('is-running')).toBe(true);
    expect(document.getElementById('analyticsPipelineTitle').textContent).toBe('Pipeline update in progress');
    expect(initializing.classList.contains('is-complete')).toBe(true);
    expect(initializing.querySelector('.pipeline-timeline__fill').style.width).toBe('100.0%');
    expect(initializing.querySelector('[data-stage-state]').textContent).toBe('✓');
    expect(matching.classList.contains('is-active')).toBe(true);
    expect(matching.querySelector('[data-stage-state]').classList.contains('is-active')).toBe(true);
    expect(matching.querySelector('.pipeline-timeline__fill').style.width).toBe('100.0%');
    expect(parseFloat(initializing.style.flexGrow)).toBe(5);
    expect(parseFloat(matching.style.flexGrow)).toBe(60);
    expect(parseFloat(importing.style.flexGrow)).toBeCloseTo(0.001);
    expect(importing.querySelector('[data-stage-duration]').textContent).toBe('Waiting');
  });

  test('updates elapsed seconds and reduces completed stages proportional share each second', () => {
    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {
        status: 'running',
        phase: 'stop_matching',
        started_at: new Date(Date.now() - 20000).toISOString(),
        phase_started_at: new Date(Date.now() - 10000).toISOString(),
        phase_history: [{
          phase: 'source_check',
          started_at: new Date(Date.now() - 25000).toISOString(),
          duration_seconds: 10
        }]
      }
    }));

    const initializing = document.querySelector('[data-pipeline-stage="source_check"]');
    const matching = document.querySelector('[data-pipeline-stage="stop_matching"]');
    const firstActiveWeight = parseFloat(matching.style.flexGrow);
    const firstInitializeShare = parseFloat(initializing.style.flexGrow) /
      (parseFloat(initializing.style.flexGrow) + firstActiveWeight);

    jest.advanceTimersByTime(1000);

    const secondActiveWeight = parseFloat(matching.style.flexGrow);
    const secondInitializeShare = parseFloat(initializing.style.flexGrow) /
      (parseFloat(initializing.style.flexGrow) + secondActiveWeight);
    expect(secondActiveWeight).toBeGreaterThan(firstActiveWeight);
    expect(secondInitializeShare).toBeLessThan(firstInitializeShare);
    expect(matching.querySelector('[data-stage-duration]').textContent).toBe('11s');
  });

  test('does not replace unchanged title text during the one-second refresh', () => {
    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {
        status: 'running',
        phase: 'stop_matching',
        message: 'Stop matching',
        started_at: new Date(Date.now() - 20000).toISOString(),
        phase_started_at: new Date(Date.now() - 10000).toISOString(),
        phase_history: []
      }
    }));

    const title = document.getElementById('analyticsPipelineTitle');
    const titleTextNode = title.firstChild;

    jest.advanceTimersByTime(1000);

    expect(title.firstChild).toBe(titleTextNode);
  });

  test('renders self-describing substages without frontend stage-specific code', () => {
    const stagePlan = [{
      id: 'osm', parent_id: null, phase: 'osm', label: 'Prepare OpenStreetMap',
      description: 'Prepare OSM', order: 40, progress_kind: 'indeterminate'
    }, {
      id: 'osm.download', parent_id: 'osm', phase: 'osm', label: 'Download OSM data from Overpass',
      description: 'Download OSM', order: 10, progress_kind: 'indeterminate'
    }, {
      id: 'osm.future_parser', parent_id: 'osm', phase: 'osm', label: 'A future parser stage',
      description: 'Added by a newer engine', order: 20, progress_kind: 'indeterminate'
    }];
    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {
        status: 'running',
        phase: 'osm',
        started_at: new Date(Date.now() - 20000).toISOString(),
        phase_started_at: new Date(Date.now() - 10000).toISOString(),
        phase_history: [],
        stage_plan: stagePlan,
        stage_states: {
          'osm.download': {status: 'complete', duration_seconds: 4},
          'osm.future_parser': {status: 'running', started_at: new Date(Date.now() - 3000).toISOString()}
        }
      }
    }));

    const details = document.querySelector('[data-progress-phase="osm"]');
    expect(details.tagName).toBe('SECTION');
    expect(details.classList.contains('is-active')).toBe(true);
    expect(details.querySelectorAll('[data-progress-stage]')).toHaveLength(2);
    expect(details.querySelector('[data-progress-stage="osm.download"] .pipeline-substage__status').textContent).toBe('Complete · 4s');
    expect(details.textContent).toContain('A future parser stage');
    expect(details.querySelector('.pipeline-stage-detail__count').textContent).toBe('Running');
  });

  test('orders late phases and children while retaining focused nodes across polling', () => {
    const root = (id, order) => ({id, parent_id: null, phase: id, label: id, description: id, order});
    const child = (id, phase, order) => ({id, parent_id: phase, phase, label: id, description: id, order});
    const appPlan = [root('osm', 40), root('database', 80), root('publish', 90),
      child('database.load', 'database', 10), child('publish.swap', 'publish', 10)];
    const render = stage_plan => document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {status: 'running', run_id: 'ordering', phase: 'osm', stage_plan, stage_states: {}}
    }));
    render(appPlan);
    const database = document.querySelector('[data-progress-phase="database"]');
    database.tabIndex = 0;
    database.focus();
    const latePlan = [...appPlan, child('osm.later', 'osm', 20)];
    render(latePlan);
    expect(Array.from(document.querySelectorAll('[data-progress-phase]'), node => node.dataset.progressPhase))
      .toEqual(['osm', 'database', 'publish']);
    expect(document.activeElement).toBe(database);
    const later = document.querySelector('[data-progress-stage="osm.later"]');
    render([...latePlan, child('osm.earlier', 'osm', 10)]);
    expect(Array.from(document.querySelector('[data-progress-phase="osm"] ul').children, node => node.dataset.progressStage))
      .toEqual(['osm.earlier', 'osm.later']);
    jest.advanceTimersByTime(1000);
    expect(document.querySelector('[data-progress-stage="osm.later"]')).toBe(later);
    expect(document.querySelector('[data-progress-phase="database"]')).toBe(database);
    expect(document.activeElement).toBe(database);
  });

  test('renders opaque stage IDs safely and removes old-run children', () => {
    const id = 'osm.parser["quoted"]';
    const root = {id: 'osm', parent_id: null, phase: 'osm', label: 'OSM', order: 40};
    const render = (run_id, children) => document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {status: 'running', phase: 'osm', run_id, stage_plan: [root, ...children], stage_states: {}}
    }));
    const spec = {id, parent_id: 'osm', phase: 'osm', label: '<b>Literal label</b>', order: 10};
    render('first', [spec]);
    render('first', [spec]);
    const items = document.querySelectorAll('[data-progress-stage]');
    expect(items).toHaveLength(1);
    expect(items[0].querySelector('b')).toBeNull();
    expect(items[0].textContent).toContain('<b>Literal label</b>');
    render('second', []);
    expect(document.querySelectorAll('[data-progress-stage]')).toHaveLength(0);
  });

  test('uses backend parent states and displays publication warnings', () => {
    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {status: 'idle', phase: 'idle', finished_at: '2026-09-21T10:00:00Z', dataset_published: true,
        warnings: ['Analytics need regeneration'], stage_states: {
          publish: {status: 'failed'}, database: {status: 'complete'}, osm: {status: 'waiting'}
        }}
    }));
    expect(document.getElementById('analyticsPipelineTitle').textContent).toBe('Dataset published with warnings');
    expect(document.getElementById('analyticsPipelineMessage').textContent).toContain('Analytics need regeneration');
    expect(document.querySelector('[data-pipeline-stage="publish"]').classList.contains('is-failed')).toBe(true);
    expect(document.querySelector('[data-pipeline-stage="publish"]').classList.contains('is-complete')).toBe(false);
    expect(document.querySelector('[data-pipeline-stage="osm"]').classList.contains('is-complete')).toBe(false);
  });

  test('keeps completed substage bullets expanded and successful', () => {
    const stagePlan = [{
      id: 'osm', parent_id: null, phase: 'osm', label: 'Prepare OpenStreetMap',
      description: 'Prepare OSM', order: 40, progress_kind: 'indeterminate'
    }, {
      id: 'osm.download', parent_id: 'osm', phase: 'osm', label: 'Download OSM data from Overpass',
      description: 'Download OSM', order: 10, progress_kind: 'indeterminate'
    }, {
      id: 'osm.prepare', parent_id: 'osm', phase: 'osm', label: 'Parse and prepare OSM data',
      description: 'Prepare OSM', order: 20, progress_kind: 'indeterminate'
    }];
    const completedStatus = {
      status: 'idle',
      phase: 'idle',
      finished_at: '2026-09-20T11:00:00Z',
      phase_history: [],
      stage_plan: stagePlan,
      stage_states: {
        'osm.download': {status: 'complete', duration_seconds: 106},
        'osm.prepare': {status: 'complete', duration_seconds: 88}
      }
    };

    document.dispatchEvent(new CustomEvent('pipeline-status:update', {detail: completedStatus}));

    const details = document.querySelector('[data-progress-phase="osm"]');
    expect(details.classList.contains('is-complete')).toBe(true);
    expect(details.querySelectorAll('.pipeline-substage.is-complete')).toHaveLength(2);
    expect(details.querySelector('.pipeline-stage-detail__count').textContent).toBe('2/2 complete');
    expect(details.querySelector('.pipeline-substage__status-label').textContent).toBe('Complete');
    expect(details.querySelector('.pipeline-substage__status-meta').textContent).toBe(' · 1m 46s');
  });

  test('lists not-yet-started substages as waiting', () => {
    const stagePlan = [{
      id: 'route_matching', parent_id: null, phase: 'route_matching', label: 'Route matching',
      description: 'Match routes', order: 60, progress_kind: 'indeterminate'
    }, {
      id: 'route_matching.families', parent_id: 'route_matching', phase: 'route_matching', label: 'Match line families',
      description: 'Match route families', order: 10, progress_kind: 'indeterminate'
    }, {
      id: 'route_matching.itineraries', parent_id: 'route_matching', phase: 'route_matching', label: 'Match itineraries',
      description: 'Match itinerary directions', order: 20, progress_kind: 'indeterminate'
    }];

    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {
        status: 'running',
        phase: 'osm',
        started_at: new Date().toISOString(),
        phase_history: [],
        stage_plan: stagePlan,
        stage_states: {}
      }
    }));

    const group = document.querySelector('[data-progress-phase="route_matching"]');
    expect(group.tagName).toBe('SECTION');
    expect(group.querySelectorAll('.pipeline-substage.is-waiting')).toHaveLength(2);
    expect(Array.from(group.querySelectorAll('.pipeline-substage__status')).map(node => node.textContent)).toEqual(['Waiting', 'Waiting']);
    expect(group.querySelector('.pipeline-stage-detail__count').textContent).toBe('0/2 complete');
  });

  test('uses a three-arrow reuse symbol instead of a relaunch arrow', () => {
    const stagePlan = [{
      id: 'atlas', parent_id: null, phase: 'atlas', label: 'Prepare ATLAS',
      description: 'Prepare ATLAS', order: 20, progress_kind: 'indeterminate'
    }, {
      id: 'atlas.prepare', parent_id: 'atlas', phase: 'atlas', label: 'Download and prepare ATLAS stops',
      description: 'Prepare ATLAS', order: 10, progress_kind: 'indeterminate'
    }];

    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {
        status: 'running', phase: 'osm', phase_history: [], stage_plan: stagePlan,
        stage_states: {'atlas.prepare': {status: 'reused'}}
      }
    }));

    const reused = document.querySelector('[data-progress-stage="atlas.prepare"]');
    expect(reused.classList.contains('is-reused')).toBe(true);
    expect(reused.querySelector('.pipeline-substage__marker').textContent).toBe('♻︎');
    expect(reused.querySelector('.pipeline-substage__status').textContent).toBe('Reused');
  });

  test('leaves every stage complete after a successful run', () => {
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

  test('keeps every stage waiting when no run has completed', () => {
    document.getElementById('pipelineRunCard').setAttribute('data-last-completed', '');
    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {
        status: 'idle',
        phase: 'idle',
        finished_at: null,
        last_success_at: null,
        last_pipeline_data_import_ended_at: null,
        phase_history: []
      }
    }));

    const stages = Array.from(document.querySelectorAll('[data-pipeline-stage]'));
    expect(stages.every(stage => !stage.classList.contains('is-complete'))).toBe(true);
    expect(stages.every(stage => stage.querySelector('.pipeline-timeline__fill').style.width === '0.0%')).toBe(true);
    expect(document.getElementById('analyticsPipelineTitle').textContent).toBe('Waiting for first pipeline run');
    expect(document.getElementById('analyticsPipelineStatus').textContent).toContain('Waiting');
  });

  test('marks the interrupted stage without presenting it as complete', () => {
    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {
        status: 'failed',
        phase: 'failed',
        failed_phase: 'stop_matching',
        last_error: 'Source unavailable',
        finished_at: '2026-09-20T11:00:00Z',
        phase_history: [{
          phase: 'stop_matching',
          started_at: '2026-09-20T10:50:00Z',
          duration_seconds: 600,
          status: 'failed'
        }]
      }
    }));

    const matching = document.querySelector('[data-pipeline-stage="stop_matching"]');
    expect(document.getElementById('pipelineRunCard').classList.contains('is-failed')).toBe(true);
    expect(matching.classList.contains('is-failed')).toBe(true);
    expect(matching.classList.contains('is-complete')).toBe(false);
    expect(parseFloat(matching.querySelector('.pipeline-timeline__fill').style.width)).toBeGreaterThan(0);
  });

  test('shows cached and inapplicable stages as reused or skipped', () => {
    document.dispatchEvent(new CustomEvent('pipeline-status:update', {
      detail: {
        status: 'running',
        phase: 'database',
        started_at: new Date(Date.now() - 10000).toISOString(),
        phase_started_at: new Date(Date.now() - 5000).toISOString(),
        phase_history: [{
          phase: 'atlas',
          started_at: '2026-09-20T10:00:01Z',
          finished_at: '2026-09-20T10:00:01Z',
          duration_seconds: 0,
          status: 'reused'
        }, {
          phase: 'timetable',
          started_at: '2026-09-20T10:00:02Z',
          finished_at: '2026-09-20T10:00:02Z',
          duration_seconds: 0,
          status: 'reused'
        }, {
          phase: 'bundle',
          started_at: '2026-09-20T10:00:03Z',
          finished_at: '2026-09-20T10:00:03Z',
          duration_seconds: 0,
          status: 'skipped'
        }],
        phase_outcomes: {
          atlas: 'reused',
          timetable: 'reused',
          bundle: 'skipped'
        }
      }
    }));

    expect(document.querySelector('[data-pipeline-stage="atlas"] [data-stage-duration]').textContent).toBe('Reused');
    expect(document.querySelector('[data-pipeline-stage="timetable"] [data-stage-duration]').textContent).toBe('Reused');
    expect(document.querySelector('[data-pipeline-stage="bundle"] [data-stage-duration]').textContent).toBe('Skipped');
    expect(document.querySelector('[data-pipeline-stage="atlas"] [data-stage-time]').textContent).not.toBe('—');
    expect(document.querySelector('[data-pipeline-stage="timetable"] [data-stage-time]').textContent).not.toBe('—');
    expect(document.querySelector('[data-pipeline-stage="bundle"] [data-stage-time]').textContent).not.toBe('—');
    expect(document.querySelector('[data-pipeline-stage="atlas"] [data-stage-time]').title).toContain('Reuse decided at');
    expect(document.querySelector('[data-pipeline-stage="bundle"] [data-stage-time]').title).toContain('Skip decided at');
  });

  test('adds an accessible tooltip only when a stage label is truncated', () => {
    const label = document.querySelector('[data-pipeline-stage="timetable"] [data-stage-label]');
    const dispose = jest.fn();
    const getOrCreateInstance = jest.fn(() => ({dispose}));
    const getInstance = jest.fn(() => ({dispose}));
    window.bootstrap = {Tooltip: {getOrCreateInstance, getInstance}};
    Object.defineProperty(label, 'clientWidth', {configurable: true, value: 70});
    Object.defineProperty(label, 'scrollWidth', {configurable: true, value: 140});

    window.dispatchEvent(new Event('resize'));

    expect(label.classList.contains('is-truncated')).toBe(true);
    expect(label.getAttribute('title')).toBe('timetable');
    expect(label.getAttribute('tabindex')).toBe('0');
    expect(getOrCreateInstance).toHaveBeenCalled();

    Object.defineProperty(label, 'scrollWidth', {configurable: true, value: 60});
    window.dispatchEvent(new Event('resize'));

    expect(label.classList.contains('is-truncated')).toBe(false);
    expect(label.hasAttribute('title')).toBe(false);
    expect(dispose).toHaveBeenCalled();
    delete window.bootstrap;
  });

  test('moves the navigation state before beginning the section scroll', () => {
    const routeLink = document.querySelector('.stats-section-nav__link[href="#routes"]');
    const routeSection = document.getElementById('routes');
    routeSection.scrollIntoView = jest.fn();

    routeLink.click();

    expect(routeLink.classList.contains('is-active')).toBe(true);
    expect(routeLink.getAttribute('aria-current')).toBe('location');
    expect(routeSection.scrollIntoView).not.toHaveBeenCalled();

    jest.advanceTimersByTime(80);

    expect(routeSection.scrollIntoView).toHaveBeenCalledWith({behavior: 'smooth', block: 'start'});
  });

  test('reserves the sticky navigation stack above section scroll targets', () => {
    const nav = document.querySelector('.stats-section-nav');
    Object.defineProperty(nav, 'offsetHeight', {configurable: true, value: 48});
    jest.spyOn(window, 'getComputedStyle').mockReturnValueOnce({top: '60px'});

    window.dispatchEvent(new Event('resize'));

    expect(document.documentElement.style.getPropertyValue('--stats-section-scroll-offset')).toBe('124px');
    window.getComputedStyle.mockRestore();
  });
});
