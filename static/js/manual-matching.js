// Manual Matching Functionality

// Global variables for manual matching 
var manualMatches = [];  // Array to hold manual match pairs
var manualSelection = null; // For manual matching workflow

// Function to check if a match already exists between two nodes
function matchExists(atlasId, osmId) {
    return manualMatches.some(function(match) {
        return (match.atlas_id === atlasId && match.osm_id === osmId) || 
               (match.atlas_id === osmId && match.osm_id === atlasId);
    });
}

// Function to redraw manual match lines
function redrawManualMatchLines() {
    // First, clear any existing manual match lines
    linesLayer.eachLayer(function(layer) {
        if (layer.options && layer.options.isManualMatch) {
            linesLayer.removeLayer(layer);
        }
    });
    
    // Redraw each manual match line
    manualMatches.forEach(function(match) {
        var atlasStop = stopsById[match.atlas_id];
        var osmStop = stopsById[match.osm_id];
        
        // Check if both stops are available (they might not be in the current viewport)
        if (atlasStop && osmStop) {
            var atlasLat = parseFloat(atlasStop.atlas_lat || atlasStop.lat);
            var atlasLon = parseFloat(atlasStop.atlas_lon || atlasStop.lon);
            var osmLat = parseFloat(osmStop.osm_lat || osmStop.lat);
            var osmLon = parseFloat(osmStop.osm_lon || osmStop.lon);
            
            // Get descriptive names for both stops
            var atlasName = atlasStop.atlas_designation || atlasStop.atlas_designation_official || atlasStop.atlas_number || atlasStop.sloid;
            var osmName = osmStop.osm_name || osmStop.osm_local_ref || osmStop.osm_node_id || "OSM Node";
            
            // Create the line with a popup
            var line = L.polyline([
                [atlasLat, atlasLon],
                [osmLat, osmLon]
            ], {
                color: "purple", 
                dashArray: "5,5",
                weight: 3,
                opacity: 0.8,
                matchId: match.id,
                isManualMatch: true  // Mark as a manual match line
            }).bindPopup(
                "<strong>Manual Match:</strong><br>" +
                "ATLAS: " + atlasName + "<br>" +
                "OSM: " + osmName + "<br>" +
                "<button class='btn btn-sm btn-danger' onclick='removeManualMatch(\"" + match.id + "\")'>Remove Match</button>",
                {autoClose: false, closeOnClick: false}
            );
            
            linesLayer.addLayer(line);
        }
    });
}

function manualMatchSelect(stopId, stopCategory) {
    var selectedStop = stopsById[stopId];
    if (!selectedStop) {
        alert("Stop data not found.");
        return;
    }
    if (stopCategory !== "atlas" && stopCategory !== "osm") {
        alert("Invalid stop category.");
        return;
    }
    
    // Get a descriptive name based on the stop category
    var stopName = stopCategory === "atlas" 
        ? (selectedStop.atlas_designation || selectedStop.atlas_designation_official || selectedStop.atlas_number || selectedStop.sloid)
        : (selectedStop.osm_name || selectedStop.osm_local_ref || selectedStop.osm_node_id || "OSM Node");
    
    if (!manualSelection) {
         manualSelection = { id: stopId, category: stopCategory, stop: selectedStop };
         alert("First stop selected: " + stopName + ". Now select a stop of the opposite type.");
    } else {
         if (manualSelection.category === stopCategory) {
             alert("Please select a stop of the opposite type (ATLAS vs. OSM).");
             return;
         }
         var atlasStop = manualSelection.category === "atlas" ? manualSelection.stop : selectedStop;
         var osmStop = manualSelection.category === "osm" ? manualSelection.stop : selectedStop;
         
         // Check if this pair is already matched
         if (matchExists(atlasStop.id, osmStop.id)) {
             alert("These stops are already matched!");
             manualSelection = null;
             return;
         }
         
         // Create a unique ID for this manual match
         var matchId = "match_" + atlasStop.id + "_" + osmStop.id;
         
         // Add to manualMatches with the matchId
         manualMatches.push({ 
             id: matchId,
             atlas_id: atlasStop.id, 
             osm_id: osmStop.id 
         });
         
         // Get descriptive names for both stops
         var atlasName = atlasStop.atlas_designation || atlasStop.atlas_designation_official || atlasStop.atlas_number || atlasStop.sloid;
         var osmName = osmStop.osm_name || osmStop.osm_local_ref || osmStop.osm_node_id || "OSM Node";
         
         alert("Matched " + atlasName + " with " + osmName);
         
         // Draw the match line
         redrawManualMatchLines();
         manualSelection = null;
    }
}

function removeManualMatch(matchId) {
    // Find the match in the array
    var matchIndex = manualMatches.findIndex(function(match) {
        return match.id === matchId;
    });
    
    if (matchIndex !== -1) {
        // Remove the match from the array
        manualMatches.splice(matchIndex, 1);
        
        // Redraw the manual match lines
        redrawManualMatchLines();
        
        // Close any open popups
        map.closePopup();
        
        alert("Match removed successfully");
    }
}

// Function to initialize manual matching UI events
function initManualMatching() {
    $('#saveChangesBtn').on('click', function(){
        var payload = { message: "User changes saved.", manualMatches: manualMatches };
        $.ajax({
            url: "/api/save",
            method: "POST",
            contentType: "application/json",
            data: JSON.stringify(payload),
            success: function(response){
                alert(response.message);
                manualMatches = [];
            },
            error: function(xhr){
                alert("Error saving changes: " + xhr.responseText);
            }
        });
    });
    
    $('#previewMatchesBtn').on('click', function(){
        if (manualMatches.length === 0) { alert("No manual matches have been made yet."); return; }
        var html = "<table class='table table-bordered'><thead><tr><th>ATLAS Sloid</th><th>OSM Node ID</th><th>ATLAS Coords</th><th>OSM Coords</th><th>Actions</th></tr></thead><tbody>";
        manualMatches.forEach(function(match) {
             var atlasStop = stopsById[match.atlas_id];
             var osmStop = stopsById[match.osm_id];
             if(atlasStop && osmStop) {
                 var atlasCoords = (atlasStop.atlas_lat && atlasStop.atlas_lon) ?
                                   (atlasStop.atlas_lat + ", " + atlasStop.atlas_lon) :
                                   (atlasStop.lat + ", " + atlasStop.lon);
                 var osmCoords = (osmStop.osm_lat && osmStop.osm_lon) ?
                                   (osmStop.osm_lat + ", " + osmStop.osm_lon) :
                                   (osmStop.lat + ", " + osmStop.lon);
                 html += "<tr><td>" + (atlasStop.sloid || atlasStop.atlas_number || "N/A") + "</td>" + 
                         "<td>" + (osmStop.osm_node_id || osmStop.osm_local_ref || "N/A") + "</td>" + 
                         "<td>" + atlasCoords + "</td>" + 
                         "<td>" + osmCoords + "</td>" + 
                         "<td><button class='btn btn-sm btn-danger' onclick='removeManualMatch(\"" + match.id + "\")'>Remove</button></td></tr>";
             }
        });
        html += "</tbody></table>";
        $("#previewModalBody").html(html);
        $("#previewModal").modal('show');
    });
}

// Export functions and variables for use in main.js
window.manualMatches = manualMatches;
window.manualSelection = manualSelection;
window.matchExists = matchExists;
window.redrawManualMatchLines = redrawManualMatchLines;
window.manualMatchSelect = manualMatchSelect;
window.removeManualMatch = removeManualMatch;
window.initManualMatching = initManualMatching; 