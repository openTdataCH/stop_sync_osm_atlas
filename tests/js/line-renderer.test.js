/**
 * Test Suite for LineRenderer Module
 * 
 * These tests verify the line drawing functionality for ATLAS-OSM matched pairs.
 * Run with Jest or any compatible test runner.
 * 
 * Setup: Mock Leaflet's L.polyline and layer methods before running tests.
 */

// ==========================================
// MOCK SETUP
// ==========================================

// Mock Leaflet's L object
const mockPolyline = {
    addTo: jest.fn().mockReturnThis()
};

const mockLayer = {
    addLayer: jest.fn(),
    eachLayer: jest.fn(),
    removeLayer: jest.fn(),
    clearLayers: jest.fn()
};

// Store calls to L.polyline for verification
let polylineCalls = [];

global.L = {
    polyline: jest.fn((coords, options) => {
        const call = { coords, options };
        polylineCalls.push(call);
        return { ...mockPolyline, _coords: coords, _options: options };
    })
};

// Import LineRenderer (assuming it's loaded globally in browser)
// In a real setup, you'd use module imports
// For this test, we'll simulate the module inline

// ==========================================
// LINERENDERER MODULE (COPY FOR TESTING)
// ==========================================

const LineRenderer = {};
const COLOR_LINE_ATLAS_OSM = '#174092';

const LINE_STYLES = {
    default: { color: COLOR_LINE_ATLAS_OSM, weight: 2, opacity: 1 },
    context: { color: COLOR_LINE_ATLAS_OSM, weight: 2, opacity: 0.4 }
};

LineRenderer.getStyle = function(matchType, isContext) {
    return isContext ? LINE_STYLES.context : LINE_STYLES.default;
};

LineRenderer._buildLineKey = function(sloid, osmNodeId) {
    const s = sloid || 'unknown_atlas';
    const o = osmNodeId || 'unknown_osm';
    return `${s}-${o}`;
};

LineRenderer._getOsmNodesFromStop = function(stop) {
    if (Array.isArray(stop.osm_matches) && stop.osm_matches.length > 0) {
        return stop.osm_matches;
    }
    if (stop.osm_node_id) {
        return [{
            osm_node_id: stop.osm_node_id,
            osm_lat: stop.osm_lat,
            osm_lon: stop.osm_lon,
            match_type: stop.match_type
        }];
    }
    return [];
};

LineRenderer._drawLinesForStop = function(stop, layer, drawnKeys, isContext) {
    if (!stop.atlas_lat || !stop.atlas_lon) return 0;
    let linesDrawn = 0;
    const osmNodes = this._getOsmNodesFromStop(stop);
    
    osmNodes.forEach((osm) => {
        if (osm.osm_lat == null || osm.osm_lon == null) return;
        const osmNodeId = osm.osm_node_id || stop.osm_node_id;
        const key = this._buildLineKey(stop.sloid, osmNodeId);
        if (drawnKeys.has(key)) return;
        drawnKeys.add(key);
        
        const style = this.getStyle(stop.match_type, isContext);
        
        const line = L.polyline([
            [parseFloat(stop.atlas_lat), parseFloat(stop.atlas_lon)],
            [parseFloat(osm.osm_lat), parseFloat(osm.osm_lon)]
        ], style);
        layer.addLayer(line);
        linesDrawn++;
    });
    
    return linesDrawn;
};

LineRenderer.drawAll = function(data, layer, options) {
    const { showAtlas, showOsm, minZoom, currentZoom, isContext } = options;
    if (currentZoom < minZoom) return 0;
    if (!showAtlas || !showOsm) return 0;
    if (!Array.isArray(data) || data.length === 0) return 0;
    
    const drawnKeys = new Set();
    let lineCount = 0;
    
    data.forEach((stop) => {
        if (stop.stop_type !== 'matched') return;
        lineCount += this._drawLinesForStop(stop, layer, drawnKeys, isContext);
    });
    
    return lineCount;
};

LineRenderer.clearLines = function(layer) {
    if (!layer) return;
    layer.clearLayers();
};

// ==========================================
// TEST SUITE
// ==========================================

describe('LineRenderer', () => {
    beforeEach(() => {
        // Reset mocks before each test
        jest.clearAllMocks();
        polylineCalls = [];
        mockLayer.addLayer.mockClear();
    });

    // -----------------------------------------
    // getStyle Tests
    // -----------------------------------------
    describe('getStyle', () => {
        test('returns ATLAS-OSM line style for standard exact match', () => {
            const style = LineRenderer.getStyle('exact', false);
            expect(style.color).toBe(COLOR_LINE_ATLAS_OSM);
            expect(style.weight).toBe(2);
        });

        test('returns ATLAS-OSM line style for distance matching', () => {
            const style = LineRenderer.getStyle('distance_matching_50', false);
            expect(style.color).toBe(COLOR_LINE_ATLAS_OSM);
        });

        test('returns ATLAS-OSM line style for name matching', () => {
            const style = LineRenderer.getStyle('name', false);
            expect(style.color).toBe(COLOR_LINE_ATLAS_OSM);
        });

        test('returns context style with lower opacity', () => {
            const style = LineRenderer.getStyle('exact', true);
            expect(style.color).toBe(COLOR_LINE_ATLAS_OSM);
            expect(style.opacity).toBe(0.4);
        });
    });

    // -----------------------------------------
    // _buildLineKey Tests
    // -----------------------------------------
    describe('_buildLineKey', () => {
        test('builds correct key from sloid and osm_node_id', () => {
            const key = LineRenderer._buildLineKey('ch:1:sloid:123', 'n12345');
            expect(key).toBe('ch:1:sloid:123-n12345');
        });

        test('handles null sloid', () => {
            const key = LineRenderer._buildLineKey(null, 'n12345');
            expect(key).toBe('unknown_atlas-n12345');
        });

        test('handles null osm_node_id', () => {
            const key = LineRenderer._buildLineKey('ch:1:sloid:123', null);
            expect(key).toBe('ch:1:sloid:123-unknown_osm');
        });

        test('handles both null', () => {
            const key = LineRenderer._buildLineKey(null, null);
            expect(key).toBe('unknown_atlas-unknown_osm');
        });
    });

    // -----------------------------------------
    // _getOsmNodesFromStop Tests
    // -----------------------------------------
    describe('_getOsmNodesFromStop', () => {
        test('returns osm_matches array when present', () => {
            const stop = {
                osm_matches: [
                    { osm_node_id: 'n1', osm_lat: 47.0, osm_lon: 8.0 },
                    { osm_node_id: 'n2', osm_lat: 47.1, osm_lon: 8.1 }
                ],
                osm_node_id: 'n3'
            };
            const nodes = LineRenderer._getOsmNodesFromStop(stop);
            expect(nodes).toHaveLength(2);
            expect(nodes[0].osm_node_id).toBe('n1');
        });

        test('returns single-element array from stop when no osm_matches', () => {
            const stop = {
                osm_node_id: 'n123',
                osm_lat: 47.5,
                osm_lon: 8.5,
                match_type: 'exact'
            };
            const nodes = LineRenderer._getOsmNodesFromStop(stop);
            expect(nodes).toHaveLength(1);
            expect(nodes[0].osm_node_id).toBe('n123');
        });

        test('returns empty array when no OSM data', () => {
            const stop = { sloid: 'ch:1:sloid:123' };
            const nodes = LineRenderer._getOsmNodesFromStop(stop);
            expect(nodes).toHaveLength(0);
        });
    });

    // -----------------------------------------
    // drawAll Tests
    // -----------------------------------------
    describe('drawAll', () => {
        test('draws no lines when zoom is below threshold', () => {
            const data = [{
                stop_type: 'matched',
                sloid: 'ch:1:sloid:1',
                atlas_lat: 47.0,
                atlas_lon: 8.0,
                osm_node_id: 'n1',
                osm_lat: 47.001,
                osm_lon: 8.001
            }];
            
            const count = LineRenderer.drawAll(data, mockLayer, {
                showAtlas: true,
                showOsm: true,
                minZoom: 13,
                currentZoom: 10, // Below threshold
                isContext: false
            });
            
            expect(count).toBe(0);
            expect(mockLayer.addLayer).not.toHaveBeenCalled();
        });

        test('draws no lines when showAtlas is false', () => {
            const data = [{
                stop_type: 'matched',
                sloid: 'ch:1:sloid:1',
                atlas_lat: 47.0,
                atlas_lon: 8.0,
                osm_node_id: 'n1',
                osm_lat: 47.001,
                osm_lon: 8.001
            }];
            
            const count = LineRenderer.drawAll(data, mockLayer, {
                showAtlas: false,
                showOsm: true,
                minZoom: 13,
                currentZoom: 15,
                isContext: false
            });
            
            expect(count).toBe(0);
        });

        test('draws line for simple 1:1 match', () => {
            const data = [{
                stop_type: 'matched',
                sloid: 'ch:1:sloid:1',
                atlas_lat: 47.0,
                atlas_lon: 8.0,
                osm_node_id: 'n1',
                osm_lat: 47.001,
                osm_lon: 8.001,
                match_type: 'exact'
            }];
            
            const count = LineRenderer.drawAll(data, mockLayer, {
                showAtlas: true,
                showOsm: true,
                minZoom: 13,
                currentZoom: 15,
                isContext: false
            });
            
            expect(count).toBe(1);
            expect(mockLayer.addLayer).toHaveBeenCalledTimes(1);
            expect(polylineCalls).toHaveLength(1);
            expect(polylineCalls[0].coords).toEqual([[47.0, 8.0], [47.001, 8.001]]);
            expect(polylineCalls[0].options.color).toBe(COLOR_LINE_ATLAS_OSM);
        });

        test('draws multiple lines for 1:N match (1 ATLAS to multiple OSM)', () => {
            const data = [{
                stop_type: 'matched',
                sloid: 'ch:1:sloid:1',
                atlas_lat: 47.0,
                atlas_lon: 8.0,
                osm_matches: [
                    { osm_node_id: 'n1', osm_lat: 47.001, osm_lon: 8.001 },
                    { osm_node_id: 'n2', osm_lat: 47.002, osm_lon: 8.002 }
                ],
                match_type: 'exact'
            }];
            
            const count = LineRenderer.drawAll(data, mockLayer, {
                showAtlas: true,
                showOsm: true,
                minZoom: 13,
                currentZoom: 15,
                isContext: false
            });
            
            expect(count).toBe(2);
            expect(mockLayer.addLayer).toHaveBeenCalledTimes(2);
        });

        test('draws multiple lines for N:1 match (multiple ATLAS to 1 OSM)', () => {
            // This is the key bug case: 2 ATLAS stops matched to same OSM node
            const data = [
                {
                    stop_type: 'matched',
                    sloid: 'ch:1:sloid:A1',
                    atlas_lat: 47.0,
                    atlas_lon: 8.0,
                    osm_matches: [{ osm_node_id: 'n1', osm_lat: 47.005, osm_lon: 8.005 }],
                    match_type: 'exact'
                },
                {
                    stop_type: 'matched',
                    sloid: 'ch:1:sloid:A2',
                    atlas_lat: 47.001,
                    atlas_lon: 8.001,
                    osm_matches: [{ osm_node_id: 'n1', osm_lat: 47.005, osm_lon: 8.005 }],
                    match_type: 'exact'
                }
            ];
            
            const count = LineRenderer.drawAll(data, mockLayer, {
                showAtlas: true,
                showOsm: true,
                minZoom: 13,
                currentZoom: 15,
                isContext: false
            });
            
            // Should draw 2 lines: A1->O1 and A2->O1
            expect(count).toBe(2);
            expect(mockLayer.addLayer).toHaveBeenCalledTimes(2);
            
            // Verify both lines have different starting points
            const coords = polylineCalls.map(c => c.coords[0]);
            expect(coords).toContainEqual([47.0, 8.0]);
            expect(coords).toContainEqual([47.001, 8.001]);
        });

        test('prevents duplicate lines with same sloid-osm_node_id pair', () => {
            // If the same pair appears twice in data, only one line should be drawn
            const data = [
                {
                    stop_type: 'matched',
                    sloid: 'ch:1:sloid:1',
                    atlas_lat: 47.0,
                    atlas_lon: 8.0,
                    osm_matches: [{ osm_node_id: 'n1', osm_lat: 47.001, osm_lon: 8.001 }]
                },
                {
                    stop_type: 'matched',
                    sloid: 'ch:1:sloid:1', // Same sloid
                    atlas_lat: 47.0,
                    atlas_lon: 8.0,
                    osm_matches: [{ osm_node_id: 'n1', osm_lat: 47.001, osm_lon: 8.001 }] // Same OSM
                }
            ];
            
            const count = LineRenderer.drawAll(data, mockLayer, {
                showAtlas: true,
                showOsm: true,
                minZoom: 13,
                currentZoom: 15,
                isContext: false
            });
            
            expect(count).toBe(1); // Only one line, not two
        });

        test('skips non-matched stops', () => {
            const data = [
                { stop_type: 'atlas_unmatched', sloid: 'ch:1:sloid:1', atlas_lat: 47.0, atlas_lon: 8.0 },
                { stop_type: 'osm_unmatched', osm_node_id: 'n1', osm_lat: 47.0, osm_lon: 8.0 }
            ];
            
            const count = LineRenderer.drawAll(data, mockLayer, {
                showAtlas: true,
                showOsm: true,
                minZoom: 13,
                currentZoom: 15,
                isContext: false
            });
            
            expect(count).toBe(0);
        });

        test('skips stops without ATLAS coordinates', () => {
            const data = [{
                stop_type: 'matched',
                sloid: 'ch:1:sloid:1',
                // No atlas_lat or atlas_lon
                osm_node_id: 'n1',
                osm_lat: 47.0,
                osm_lon: 8.0
            }];
            
            const count = LineRenderer.drawAll(data, mockLayer, {
                showAtlas: true,
                showOsm: true,
                minZoom: 13,
                currentZoom: 15,
                isContext: false
            });
            
            expect(count).toBe(0);
        });

        test('handles empty data array', () => {
            const count = LineRenderer.drawAll([], mockLayer, {
                showAtlas: true,
                showOsm: true,
                minZoom: 13,
                currentZoom: 15,
                isContext: false
            });
            
            expect(count).toBe(0);
        });
    });

    // -----------------------------------------
    // clearLines Tests
    // -----------------------------------------
    describe('clearLines', () => {
        test('calls clearLayers on the layer', () => {
            LineRenderer.clearLines(mockLayer);
            expect(mockLayer.clearLayers).toHaveBeenCalled();
        });

        test('handles null layer gracefully', () => {
            expect(() => LineRenderer.clearLines(null)).not.toThrow();
        });
    });
});

// ==========================================
// INTEGRATION TEST SCENARIOS
// ==========================================

describe('LineRenderer Integration Scenarios', () => {
    beforeEach(() => {
        jest.clearAllMocks();
        polylineCalls = [];
    });

    test('Scenario: Complex N:M match with duplicates', () => {
        // Scenario: 3 ATLAS stops, 2 OSM nodes with overlapping matches
        // A1 -> O1
        // A2 -> O1, O2
        // A3 -> O2
        const data = [
            {
                stop_type: 'matched',
                sloid: 'A1',
                atlas_lat: 47.0,
                atlas_lon: 8.0,
                osm_matches: [{ osm_node_id: 'O1', osm_lat: 47.1, osm_lon: 8.1 }]
            },
            {
                stop_type: 'matched',
                sloid: 'A2',
                atlas_lat: 47.01,
                atlas_lon: 8.01,
                osm_matches: [
                    { osm_node_id: 'O1', osm_lat: 47.1, osm_lon: 8.1 },
                    { osm_node_id: 'O2', osm_lat: 47.2, osm_lon: 8.2 }
                ]
            },
            {
                stop_type: 'matched',
                sloid: 'A3',
                atlas_lat: 47.02,
                atlas_lon: 8.02,
                osm_matches: [{ osm_node_id: 'O2', osm_lat: 47.2, osm_lon: 8.2 }]
            }
        ];
        
        const count = LineRenderer.drawAll(data, mockLayer, {
            showAtlas: true,
            showOsm: true,
            minZoom: 13,
            currentZoom: 15,
            isContext: false
        });
        
        // Expected lines: A1-O1, A2-O1, A2-O2, A3-O2 = 4 unique lines
        expect(count).toBe(4);
    });

    test('Scenario: Same stop appearing multiple times in data', () => {
        // Can happen due to API quirks or data duplication
        const stop = {
            stop_type: 'matched',
            sloid: 'A1',
            atlas_lat: 47.0,
            atlas_lon: 8.0,
            osm_matches: [{ osm_node_id: 'O1', osm_lat: 47.1, osm_lon: 8.1 }]
        };
        
        const data = [stop, stop, stop]; // Same stop 3 times
        
        const count = LineRenderer.drawAll(data, mockLayer, {
            showAtlas: true,
            showOsm: true,
            minZoom: 13,
            currentZoom: 15,
            isContext: false
        });
        
        // Should only draw 1 line due to deduplication
        expect(count).toBe(1);
    });

    test('Scenario: Mixed match types with proper styling', () => {
        const data = [
            {
                stop_type: 'matched',
                sloid: 'A1',
                atlas_lat: 47.0,
                atlas_lon: 8.0,
                osm_node_id: 'O1',
                osm_lat: 47.1,
                osm_lon: 8.1,
                match_type: 'exact'
            },
            {
                stop_type: 'matched',
                sloid: 'A2',
                atlas_lat: 47.01,
                atlas_lon: 8.01,
                osm_node_id: 'O2',
                osm_lat: 47.11,
                osm_lon: 8.11,
                match_type: 'name'
            },
            {
                stop_type: 'matched',
                sloid: 'A3',
                atlas_lat: 47.02,
                atlas_lon: 8.02,
                osm_node_id: 'O3',
                osm_lat: 47.12,
                osm_lon: 8.12,
                match_type: 'distance_matching_50'
            }
        ];

        LineRenderer.drawAll(data, mockLayer, {
            showAtlas: true,
            showOsm: true,
            minZoom: 13,
            currentZoom: 15,
            isContext: false
        });

        // All match types use the same ATLAS-OSM line style
        expect(polylineCalls[0].options.color).toBe(COLOR_LINE_ATLAS_OSM);
        expect(polylineCalls[1].options.color).toBe(COLOR_LINE_ATLAS_OSM);
        expect(polylineCalls[2].options.color).toBe(COLOR_LINE_ATLAS_OSM);
    });
});
