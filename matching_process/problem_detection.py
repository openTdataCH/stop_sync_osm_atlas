"""
Problem Detection Module for Transit Stop Matching

This module contains functions to automatically detect problems in the transit stop
matching process and flag them appropriately in the database.

Problem Types:
1. Distance Problems: When matched stops have distances that exceed acceptable thresholds
2. Isolated Problems: When stops exist in one dataset but have no counterpart in the other
3. Attributes Problems: When matched stops have conflicting attribute information

Author: Transit Data Matching System
"""

import logging
from typing import Dict, List, Tuple, Any

# Setup logging
logger = logging.getLogger(__name__)

# Configuration constants
DISTANCE_PROBLEM_THRESHOLD = 25  # meters - distance above which to flag as problematic
ISOLATION_CHECK_RADIUS = 50      # meters - radius to check for isolation

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
        distance = match_record.get('distance_m')
        if distance is None:
            return False
            
        # Convert to float and check threshold
        distance_float = float(distance)
        return distance_float > DISTANCE_PROBLEM_THRESHOLD
        
    except (ValueError, TypeError) as e:
        logger.warning(f"Error processing distance for match record: {e}")
        return False

def detect_isolated_problems(stop_type: str, match_type: str = None, is_isolated_osm: bool = False) -> bool:
    """
    Detect if a stop is isolated (has no counterpart in the other dataset within 50m).
    
    Isolated problems are flagged when:
    - An unmatched ATLAS stop has no OSM counterpart within 50 meters (flagged as 'no_osm_within_50m').
    - An unmatched OSM stop has no ATLAS counterpart within 50 meters (flagged by 'is_isolated_osm').
    
    Args:
        stop_type: Type of stop ('unmatched', 'osm', 'matched', etc.)
        match_type: Additional matching information (e.g., 'no_osm_within_50m')
        is_isolated_osm: Flag indicating if an unmatched OSM node is isolated.
        
    Returns:
        bool: True if isolation problem detected, False otherwise
    """
    # An unmatched ATLAS stop is isolated only if it's explicitly flagged as having no nearby OSM nodes.
    if stop_type == 'unmatched' and match_type == 'no_osm_within_50m':
        return True
    
    # An unmatched OSM stop is isolated only if it's explicitly flagged.
    if stop_type == 'osm' and is_isolated_osm:
        return True
        
    return False

def detect_attribute_problems(match_record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Detect attribute mismatches between matched ATLAS and OSM entries.
    
    Current implementation focuses on operator mismatches, but is designed
    to be extensible for other attribute comparisons.
    
    Attribute problems are flagged when:
    - Operator names don't match between ATLAS and OSM
    - Names are significantly different (future enhancement)
    - Transport types don't align (future enhancement)
    
    Args:
        match_record: Dictionary containing match information
        
    Returns:
        Tuple[bool, List[str]]: (has_problem, list_of_mismatch_descriptions)
    """
    mismatches = []
    
    try:
        # Extract operator information, ensuring they are strings before stripping
        atlas_operator = str(match_record.get('csv_business_org_abbr', '') or '').strip()
        osm_operator = str(match_record.get('osm_operator', '') or '').strip()
        
        # Check operator mismatch
        if atlas_operator and osm_operator:
            if atlas_operator.lower() != osm_operator.lower():
                mismatches.append(f"Operator mismatch: ATLAS='{atlas_operator}' vs OSM='{osm_operator}'")
        
        # Future enhancements can add more attribute checks here:
        # - Name similarity checks
        # - Transport type alignment
        # - Reference number consistency
        # - Station vs platform type mismatches
        
        return len(mismatches) > 0, mismatches
        
    except Exception as e:
        logger.warning(f"Error detecting attribute problems: {e}")
        return False, []

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
            'isolated_problem': bool, 
            'attributes_problem': bool,
            'problem_details': List[str]
        }
    """
    result = {
        'distance_problem': False,
        'isolated_problem': False,
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
        
        # Check isolation problems
        is_isolated_osm_flag = stop_data.get('is_isolated', False)
        result['isolated_problem'] = detect_isolated_problems(
            stop_data.get('stop_type'),
            stop_data.get('match_type'),
            is_isolated_osm=is_isolated_osm_flag
        )
        if result['isolated_problem']:
            result['problem_details'].append(f"Isolation problem: {stop_data.get('stop_type')} stop")
        
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
            problem.get('isolated_problem', False), 
            problem.get('attributes_problem', False)
        ])
        
        if problem.get('distance_problem', False):
            stats['distance_problems'] += 1
        if problem.get('isolated_problem', False):
            stats['isolated_problems'] += 1
        if problem.get('attributes_problem', False):
            stats['attributes_problems'] += 1
            
        if problem_count > 1:
            stats['multiple_problems'] += 1
        elif problem_count == 0:
            stats['no_problems'] += 1
    
    return stats 