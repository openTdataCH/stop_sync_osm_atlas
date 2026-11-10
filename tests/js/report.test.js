const loadBrowserScript = require('./load-browser-script');
const path = require('path');

const flush = async () => { for (let i = 0; i < 10; i++) await Promise.resolve(); };

const OVERLAY = `
  <div id="reportLoadingOverlay" style="display: none;">
    <span id="overlayTitle"></span>
    <div id="reportProgressBar" class="progress-bar"></div>
    <strong id="progressText"></strong>
    <div id="progressCounters"><span id="entriesProcessed"></span> of <span id="totalEntries"></span></div>
    <div id="downloadSection" style="display: none;"></div>
    <div id="errorSection" style="display: none;"><span id="errorMessage"></span></div>
    <div id="progressControls"><button type="button" id="cancelReportBtn">Cancel</button></div>
  </div>`;

describe('report request params', () => {
  beforeAll(() => {
    global.OperatorDropdown = function () {};
    loadBrowserScript(path.join(__dirname, '../../static/js/pages/report.js'));
  });

  beforeEach(() => {
    document.body.innerHTML = `
      <input type="radio" name="reportCategory" value="distance" id="categoryDistance">
      <input type="radio" name="reportCategory" value="unmatched" id="categoryUnmatched">
      <input type="radio" name="reportCategory" value="problems" id="categoryProblems" checked>
      <input type="radio" name="limitMode" value="all" id="limitAll" checked>
      <input type="radio" name="limitMode" value="upto" id="limitUpTo">
      <select id="sortOrderModal"><option value="priority_desc" selected>Priority</option></select>
      <select id="reportFormatModal"><option value="csv" selected>CSV</option></select>
      <input type="number" id="reportLimitModal" value="50">
      <input type="checkbox" id="includeAtlasCoords">
      <input type="checkbox" id="includeOsmCoords">
      <input type="checkbox" id="ptypeDistance" checked>
      <input type="checkbox" id="ptypeUnmatched" checked>
      <input type="checkbox" id="ptypeAttributes" checked>
      <input type="checkbox" id="ptypeContradictsRouteMatching" checked>
      <input type="checkbox" id="ptypeDuplicates" checked>
      <input type="checkbox" id="priority1" checked>
      <input type="checkbox" id="priority2" checked>
      <input type="checkbox" id="priority3" checked>
    `;
    window.operatorDropdownReports = null;
  });

  test('includes route contradiction problem type in problems export params', () => {
    const params = window.buildReportRequestParams();

    expect(params.report_type).toBe('problems');
    expect(params.problem_types.split(',')).toEqual([
      'distance',
      'unmatched',
      'attributes',
      'contradicts_route_matching',
      'duplicates'
    ]);
    expect(params.priorities).toBe('1,2,3');
    expect(params.limit).toBe('all');
  });

  test('an unmatched export with no source ticked asks for both', () => {
    document.getElementById('categoryUnmatched').checked = true;
    document.getElementById('limitUpTo').checked = true;
    document.getElementById('includeOsmCoords').checked = true;

    expect(window.buildReportRequestParams()).toEqual({
      limit: '50', sort: 'priority_desc', report_type: 'unmatched', format: 'csv',
      include_fields: 'osm_coords', sources: 'atlas,osm'
    });
  });
});

describe('export progress overlay', () => {
  let fetchJson;
  let requests;

  beforeAll(() => {
    loadBrowserScript(path.join(__dirname, '../../static/js/components/export-progress.js'));
  });

  beforeEach(() => {
    jest.useFakeTimers();
    document.body.innerHTML = OVERLAY;
    requests = [];
    fetchJson = jest.spyOn(SharedUtils, 'fetchJson').mockImplementation((url, params, options) => {
      return new Promise((resolve, reject) => requests.push({ url, options, resolve, reject }));
    });
  });

  afterEach(() => {
    fetchJson.mockRestore();
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
    delete global.fetch;
  });

  const overlay = () => document.getElementById('reportLoadingOverlay');

  test('starts a task, polls it and downloads the finished file', async () => {
    window.URL.createObjectURL = jest.fn(() => 'blob:report');
    window.URL.revokeObjectURL = jest.fn();
    global.fetch = jest.fn(() => Promise.resolve({
      ok: true,
      headers: { get: name => (name === 'content-disposition' ? 'attachment; filename="report.csv"' : '') },
      blob: () => Promise.resolve(new Blob(['a,b']))
    }));
    const clicks = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    ExportProgress.open('Generating Summary PDF');
    expect(overlay().style.display).toBe('');
    expect(document.getElementById('overlayTitle').textContent).toBe('Generating Summary PDF');

    ExportProgress.start({ generateUrl: '/api/generate_report_async', params: { report_type: 'distance' }, showCounters: true });
    expect(requests[0].url).toBe('/api/generate_report_async');
    expect(requests[0].options).toMatchObject({ method: 'POST', body: { report_type: 'distance' } });
    requests[0].resolve({ task_id: 't1' });
    await flush();

    jest.advanceTimersByTime(1500);
    expect(requests[1].url).toBe('/api/report_progress/t1');
    requests[1].resolve({ status: 'processing', processed: 5, total: 10 });
    await flush();
    expect(document.getElementById('entriesProcessed').textContent).toBe('5');
    expect(document.getElementById('progressCounters').style.display).toBe('');

    jest.advanceTimersByTime(1500);
    requests[2].resolve({ status: 'completed', processed: 10, total: 10 });
    await flush();
    expect(document.getElementById('progressText').textContent).toBe('Complete!');
    expect(document.getElementById('downloadSection').style.display).toBe('');

    jest.advanceTimersByTime(500);
    await flush();
    expect(global.fetch).toHaveBeenCalledWith('/api/download_report/t1', expect.objectContaining({ method: 'GET' }));
    expect(clicks).toHaveBeenCalledTimes(1);
    jest.advanceTimersByTime(1000);
    expect(overlay().style.display).toBe('none');
    // Polling stopped with the completed task.
    expect(requests).toHaveLength(3);
    clicks.mockRestore();
  });

  test('a refused start says why, and Cancel stops the task on the server', async () => {
    ExportProgress.open();
    ExportProgress.start({ generateUrl: '/api/docs/generate_pdf_async', params: {} });
    const error = new Error('Request failed with status 429');
    error.status = 429;
    requests[0].reject(error);
    await flush();
    expect(document.getElementById('errorMessage').textContent).toMatch(/^Error starting task: Rate limit exceeded/);

    ExportProgress.open();
    ExportProgress.start({ generateUrl: '/api/docs/generate_pdf_async', cancelUrl: '/api/docs/cancel_pdf/', params: {} });
    requests[1].resolve({ task_id: 'doc' });
    await flush();
    document.getElementById('cancelReportBtn').click();
    expect(requests[2].url).toBe('/api/docs/cancel_pdf/doc');
    expect(requests[2].options.method).toBe('POST');
    requests[2].resolve({});
    await flush();
    expect(overlay().style.display).toBe('none');
    jest.advanceTimersByTime(3000);
    expect(requests).toHaveLength(3);
  });
});
