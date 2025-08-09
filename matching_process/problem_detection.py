"""
Problem Detection Module
This module contains functions to automatically detect problems and flag them appropriately in the database.

Problem Types:
1. Distance Problems: When matched stops have distances that exceed acceptable thresholds
2. Isolated Problems: When stops exist in one dataset but have no counterpart in the other
3. Attributes Problems: When matched stops have conflicting attribute information
"""

import logging
import numpy as np
from typing import Dict, List, Tuple, Any, Optional, Union
from scipy.spatial import KDTree

# Import centralized configuration
from .detection_config import (
    get_distance_problem_threshold,
    get_isolation_radius,
    ENABLE_OPERATOR_MISMATCH_CHECK,
    ENABLE_NAME_MISMATCH_CHECK,
    ENABLE_UIC_MISMATCH_CHECK,
    ENABLE_LOCAL_REF_MISMATCH_CHECK
)

# Setup logging
logger = logging.getLogger(__name__)

def _is_sbb(operator: Optional[str]) -> bool:
    if not operator:
        return False
    return str(operator).strip().upper() == 'SBB'

def compute_distance_priority(match_record: Dict[str, Any]) -> Optional[int]:
    """
    Compute priority for distance discrepancies.
    Rules:
      - P1: Atlas operator is not SBB AND distance > 80 m
      - P2: Atlas operator is not SBB AND 25 < distance <= 80 m
      - P3: Atlas operator is SBB AND distance > 25 m
           OR 15 < distance <= 25 m (any operator)
      - None: distance <= 15 m or missing
    """
    try:
        distance = match_record.get('distance_m')
        if distance is None:
            return None
        d = float(distance)
        atlas_operator = match_record.get('csv_business_org_abbr')
        is_sbb = _is_sbb(atlas_operator)

        if d > 80 and not is_sbb:
            return 1
        if d > 25 and d <= 80 and not is_sbb:
            return 2
        if d > 25 and is_sbb:
            return 3
        if d > 15 and d <= 25:
            return 3
        return None
    except Exception:
        return None

def detect_distance_problems(match_record: Dict[str, Any]) -> bool:
    """
    Detect if a matched pair has distance-related problems.
    
    A distance problem is flagged when:
    - The distance between matched ATLAS and OSM entries exceeds the threshold
    - This suggests potential matching errors or data quality issues
    
    Args:
        match_record: Dictionary containing match information with 'distance_m' key
        
    Returns:
        bool: True if distance problem detected, False otherwise
    """
    try:
        # Use priority computation to decide if it's a problem
        return compute_distance_priority(match_record) is not None
    except Exception as e:
        logger.warning(f"Error processing distance for match record: {e}")
        return False

def detect_unmatched_problems(stop_type: str, match_type: str = None, is_isolated: bool = False) -> bool:
    """
    Detect if a stop is unmatched (has no counterpart in the other dataset).
    
    Unmatched problems are flagged when:
    - An unmatched ATLAS stop has no OSM counterpart within the isolation radius
    - An unmatched OSM stop has no ATLAS counterpart within the isolation radius
    
    Args:
        stop_type: Type of stop ('unmatched', 'osm', 'matched', etc.)
        match_type: Additional matching information (e.g., 'no_nearby_counterpart')
        is_isolated: Flag indicating if the stop is isolated (unified for both ATLAS and OSM)
        
    Returns:
        bool: True if unmatched problem detected, False otherwise
    """
    # Any unmatched ATLAS or standalone OSM entry is an unmatched problem.
    if stop_type in ('unmatched', 'osm'):
        return True
    # Also consider explicit flag from matching stage
    if match_type == 'no_nearby_counterpart' or is_isolated:
        return True
    return False

def detect_attribute_problems(match_record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Detect attribute mismatches between matched ATLAS and OSM entries.
    
    Attribute problems are flagged when any of the following don't match:
    - Operator names: ATLAS csv_business_org_abbr vs OSM osm_operator
    - Name references: ATLAS atlas_designation_official vs OSM osm_uic_name  
    - Local references: ATLAS atlas_designation vs OSM osm_local_ref
    - UIC references: ATLAS uic_ref vs OSM uic_ref
    
    Args:
        match_record: Dictionary containing match information
        
    Returns:
        Tuple[bool, List[str]]: (has_problem, list_of_mismatch_descriptions)
    """
    mismatches = []
    
    try:
        # 1. Operator mismatch check
        if ENABLE_OPERATOR_MISMATCH_CHECK:
            atlas_operator = str(match_record.get('csv_business_org_abbr', '') or '').strip()
            osm_operator = str(match_record.get('osm_operator', '') or '').strip()
            
            if atlas_operator and osm_operator:
                if atlas_operator.lower() != osm_operator.lower():
                    mismatches.append(f"Operator mismatch: ATLAS='{atlas_operator}' vs OSM='{osm_operator}'")
        
        # 2. Name mismatch check (designation_official vs uic_name)
        if ENABLE_NAME_MISMATCH_CHECK:
            # For matched records, try csv_designation_official first, fallback to designationOfficial
            atlas_name = str(match_record.get('csv_designation_official', '') or 
                           match_record.get('designationOfficial', '') or '').strip()
            osm_name = str(match_record.get('osm_uic_name', '') or '').strip()
            
            if atlas_name and osm_name:
                if atlas_name.lower() != osm_name.lower():
                    mismatches.append(f"Name mismatch: ATLAS='{atlas_name}' vs OSM='{osm_name}'")
        
        # 3. Local reference mismatch check (designation vs local_ref)
        if ENABLE_LOCAL_REF_MISMATCH_CHECK:
            # For matched records, try csv_designation first, fallback to designation
            atlas_local_ref = str(match_record.get('csv_designation', '') or 
                                match_record.get('designation', '') or '').strip()
            osm_local_ref = str(match_record.get('osm_local_ref', '') or '').strip()
            
            if atlas_local_ref and osm_local_ref:
                if atlas_local_ref.lower() != osm_local_ref.lower():
                    mismatches.append(f"Local ref mismatch: ATLAS='{atlas_local_ref}' vs OSM='{osm_local_ref}'")
        
        # 4. UIC reference mismatch check
        if ENABLE_UIC_MISMATCH_CHECK:
            # Extract UIC references from both sources
            atlas_uic = str(match_record.get('number', '') or '').strip()  # ATLAS UIC is stored in 'number' field
            osm_uic = str(match_record.get('osm_uic_ref', '') or '').strip()
            
            if atlas_uic and osm_uic:
                if atlas_uic != osm_uic:  # UIC refs should match exactly (no case conversion)
                    mismatches.append(f"UIC ref mismatch: ATLAS='{atlas_uic}' vs OSM='{osm_uic}'")
        
        return len(mismatches) > 0, mismatches
        
    except Exception as e:
        logger.warning(f"Error detecting attribute problems: {e}")
        return False, []

def compute_attributes_priority(match_record: Dict[str, Any]) -> Optional[int]:
    """
    Compute priority for attribute mismatches.
    Rules:
      - P1: Different UIC number OR different name
      - P2: Different local ref
      - P3: Different operator
      - None: No mismatches
    """
    try:
        # UIC mismatch
        atlas_uic = str(match_record.get('number', '') or '').strip()
        osm_uic = str(match_record.get('osm_uic_ref', '') or '').strip()
        if atlas_uic and osm_uic and atlas_uic != osm_uic and ENABLE_UIC_MISMATCH_CHECK:
            return 1

        # Name mismatch (designation_official vs uic_name)
        atlas_name = str(match_record.get('csv_designation_official', '') or match_record.get('designationOfficial', '') or '').strip()
        osm_name = str(match_record.get('osm_uic_name', '') or '').strip()
        if atlas_name and osm_name and atlas_name.lower() != osm_name.lower() and ENABLE_NAME_MISMATCH_CHECK:
            return 1

        # Local ref mismatch (designation vs local_ref)
        atlas_local_ref = str(match_record.get('csv_designation', '') or match_record.get('designation', '') or '').strip()
        osm_local_ref = str(match_record.get('osm_local_ref', '') or '').strip()
        if atlas_local_ref and osm_local_ref and atlas_local_ref.lower() != osm_local_ref.lower() and ENABLE_LOCAL_REF_MISMATCH_CHECK:
            return 2

        # Operator mismatch
        atlas_operator = str(match_record.get('csv_business_org_abbr', '') or '').strip()
        osm_operator = str(match_record.get('osm_operator', '') or '').strip()
        if atlas_operator and osm_operator and atlas_operator.lower() != osm_operator.lower() and ENABLE_OPERATOR_MISMATCH_CHECK:
            return 3

        return None
    except Exception:
        return None


# ============================================================================
# CENTRALIZED ISOLATION DETECTION FUNCTIONS
# ============================================================================

def detect_atlas_isolation(atlas_stops: List[Dict[str, Any]], 
                          osm_nodes: List[Dict[str, Any]], 
                          radius_m: Optional[int] = None) -> Dict[str, bool]:
    """
    Detect which ATLAS stops are isolated (have no nearby OSM counterparts).
    
    Args:
        atlas_stops: List of ATLAS stop dictionaries with 'lat', 'lon', and identifier keys
        osm_nodes: List of OSM node dictionaries with 'lat', 'lon' keys  
        radius_m: Isolation check radius in meters (uses config default if None)
        
    Returns:
        Dict mapping ATLAS stop identifiers to isolation status (True = isolated)
    """
    if radius_m is None:
        radius_m = get_isolation_radius()
        
    # Return empty dict if no data
    if not atlas_stops or not osm_nodes:
        return {}
    
    isolation_status = {}
    
    try:
        # Create spatial index from OSM nodes for efficient proximity searches
        osm_coords = []
        for node in osm_nodes:
            lat, lon = node.get('lat'), node.get('lon')
            if lat is not None and lon is not None:
                lat_rad = np.radians(float(lat))
                lon_rad = np.radians(float(lon))
                # Convert to 3D Cartesian coordinates for KDTree
                x = np.cos(lat_rad) * np.cos(lon_rad)
                y = np.cos(lat_rad) * np.sin(lon_rad)  
                z = np.sin(lat_rad)
                osm_coords.append([x, y, z])
        
        if not osm_coords:
            # No valid OSM coordinates - all ATLAS stops are isolated
            for stop in atlas_stops:
                identifier = _get_atlas_identifier(stop)
                if identifier:
                    isolation_status[identifier] = True
            return isolation_status
            
        osm_kdtree = KDTree(osm_coords)
        
        # Convert radius from meters to approximate radians for KDTree query
        radius_rad = 2 * np.sin((radius_m / 6371000.0) / 2)  # Earth radius in meters
        
        # Check each ATLAS stop for nearby OSM nodes
        for stop in atlas_stops:
            identifier = _get_atlas_identifier(stop)
            if not identifier:
                continue
                
            lat, lon = stop.get('lat'), stop.get('lon')
            if lat is None or lon is None:
                # Invalid coordinates - consider isolated
                isolation_status[identifier] = True
                continue
                
            try:
                lat_rad = np.radians(float(lat))
                lon_rad = np.radians(float(lon))
                query_point = [
                    np.cos(lat_rad) * np.cos(lon_rad),
                    np.cos(lat_rad) * np.sin(lon_rad),
                    np.sin(lat_rad)
                ]
                
                # Find OSM nodes within radius
                indices = osm_kdtree.query_ball_point(query_point, radius_rad)
                isolation_status[identifier] = len(indices) == 0
                
            except (ValueError, TypeError) as e:
                logger.warning(f"Error processing coordinates for ATLAS stop {identifier}: {e}")
                isolation_status[identifier] = True
                
    except Exception as e:
        logger.error(f"Error in ATLAS isolation detection: {e}")
        # Fallback: mark all stops as non-isolated to avoid false positives
        for stop in atlas_stops:
            identifier = _get_atlas_identifier(stop)
            if identifier:
                isolation_status[identifier] = False
    
    return isolation_status


def detect_osm_isolation(osm_nodes: List[Dict[str, Any]], 
                        atlas_stops: List[Dict[str, Any]], 
                        radius_m: Optional[int] = None) -> Dict[str, bool]:
    """
    Detect which OSM nodes are isolated (have no nearby ATLAS counterparts).
    
    Args:
        osm_nodes: List of OSM node dictionaries with 'lat', 'lon', 'node_id' keys
        atlas_stops: List of ATLAS stop dictionaries with 'lat', 'lon' keys
        radius_m: Isolation check radius in meters (uses config default if None)
        
    Returns:
        Dict mapping OSM node IDs to isolation status (True = isolated)
    """
    if radius_m is None:
        radius_m = get_isolation_radius()
        
    # Return empty dict if no data
    if not osm_nodes or not atlas_stops:
        return {}
    
    isolation_status = {}
    
    try:
        # Create spatial index from ATLAS stops for efficient proximity searches
        atlas_coords = []
        for stop in atlas_stops:
            lat, lon = stop.get('lat'), stop.get('lon')
            if lat is not None and lon is not None:
                lat_rad = np.radians(float(lat))
                lon_rad = np.radians(float(lon))
                # Convert to 3D Cartesian coordinates for KDTree
                x = np.cos(lat_rad) * np.cos(lon_rad)
                y = np.cos(lat_rad) * np.sin(lon_rad)
                z = np.sin(lat_rad)
                atlas_coords.append([x, y, z])
        
        if not atlas_coords:
            # No valid ATLAS coordinates - all OSM nodes are isolated
            for node in osm_nodes:
                node_id = _get_osm_identifier(node)
                if node_id:
                    isolation_status[node_id] = True
            return isolation_status
            
        atlas_kdtree = KDTree(atlas_coords)
        
        # Convert radius from meters to approximate radians for KDTree query
        radius_rad = 2 * np.sin((radius_m / 6371000.0) / 2)  # Earth radius in meters
        
        # Check each OSM node for nearby ATLAS stops
        for node in osm_nodes:
            node_id = _get_osm_identifier(node)
            if not node_id:
                continue
                
            lat, lon = node.get('lat'), node.get('lon')
            if lat is None or lon is None:
                # Invalid coordinates - consider isolated
                isolation_status[node_id] = True
                continue
                
            try:
                lat_rad = np.radians(float(lat))
                lon_rad = np.radians(float(lon))
                query_point = [
                    np.cos(lat_rad) * np.cos(lon_rad),
                    np.cos(lat_rad) * np.sin(lon_rad),
                    np.sin(lat_rad)
                ]
                
                # Find ATLAS stops within radius
                indices = atlas_kdtree.query_ball_point(query_point, radius_rad)
                isolation_status[node_id] = len(indices) == 0
                
            except (ValueError, TypeError) as e:
                logger.warning(f"Error processing coordinates for OSM node {node_id}: {e}")
                isolation_status[node_id] = True
                
    except Exception as e:
        logger.error(f"Error in OSM isolation detection: {e}")
        # Fallback: mark all nodes as non-isolated to avoid false positives
        for node in osm_nodes:
            node_id = _get_osm_identifier(node)
            if node_id:
                isolation_status[node_id] = False
    
    return isolation_status


def _get_atlas_identifier(stop: Dict[str, Any]) -> Optional[str]:
    """Extract identifier from ATLAS stop dictionary."""
    # Try different possible identifier keys
    for key in ['sloid', 'id', 'stop_id']:
        if key in stop and stop[key] is not None:
            return str(stop[key])
    return None


def _get_osm_identifier(node: Dict[str, Any]) -> Optional[str]:
    """Extract identifier from OSM node dictionary.""" 
    # Try different possible identifier keys
    for key in ['node_id', 'id', 'osm_id']:
        if key in node and node[key] is not None:
            return str(node[key])
    return None

def analyze_stop_problems(stop_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Comprehensive analysis of problems for a single stop entry.
    
    This function coordinates all problem detection and returns a summary
    of issues found with the stop data.
    
    Args:
        stop_data: Dictionary containing all stop information
        
    Returns:
        Dict with problem flags and details:
        {
            'distance_problem': bool,
            'unmatched_problem': bool, 
            'attributes_problem': bool,
            'problem_details': List[str]
        }
    """
    result = {
        'distance_problem': False,
        'unmatched_problem': False,
        'attributes_problem': False,
        'problem_details': []
    }
    
    try:
        # Check distance problems (only for matched entries)
        if stop_data.get('stop_type') == 'matched':
            result['distance_problem'] = detect_distance_problems(stop_data)
            if result['distance_problem']:
                distance = stop_data.get('distance_m', 'unknown')
                result['problem_details'].append(f"Distance problem: {distance}m exceeds threshold")
        
        # Check unmatched problems
        is_isolated_flag = stop_data.get('is_isolated', False)
        result['unmatched_problem'] = detect_unmatched_problems(
            stop_data.get('stop_type'),
            stop_data.get('match_type'),
            is_isolated=is_isolated_flag
        )
        if result['unmatched_problem']:
            result['problem_details'].append(f"Unmatched problem: {stop_data.get('stop_type')} stop")
        
        # Check attribute problems (only for matched entries)
        if stop_data.get('stop_type') == 'matched':
            has_attr_problem, attr_details = detect_attribute_problems(stop_data)
            result['attributes_problem'] = has_attr_problem
            if has_attr_problem:
                result['problem_details'].extend(attr_details)
        
        return result
        
    except Exception as e:
        logger.error(f"Error in comprehensive stop analysis: {e}")
        return result

def get_problem_statistics(all_problems: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Generate statistics about detected problems for reporting.
    
    Args:
        all_problems: List of problem analysis results
        
    Returns:
        Dictionary with problem counts and statistics
    """
    stats = {
        'total_entries': len(all_problems),
        'distance_problems': 0,
        'isolated_problems': 0,
        'attributes_problems': 0,
        'multiple_problems': 0,
        'no_problems': 0
    }
    
    for problem in all_problems:
        problem_count = sum([
            problem.get('distance_problem', False),
            problem.get('unmatched_problem', False), 
            problem.get('attributes_problem', False)
        ])
        
        if problem.get('distance_problem', False):
            stats['distance_problems'] += 1
        if problem.get('unmatched_problem', False):
            stats['isolated_problems'] += 1
        if problem.get('attributes_problem', False):
            stats['attributes_problems'] += 1
            
        if problem_count > 1:
            stats['multiple_problems'] += 1
        elif problem_count == 0:
            stats['no_problems'] += 1
    
    return stats 