"""
This module centralizes all thresholds and constants used for problem detection.
"""
# ============================================================================
# ISOLATION DETECTION THRESHOLDS
# ============================================================================

# Primary radius used to determine if a stop is isolated (no counterpart nearby)
ISOLATION_CHECK_RADIUS_M = 50  # meters

# ============================================================================
# DISTANCE PROBLEM THRESHOLDS  
# ============================================================================

# Maximum acceptable distance between matched ATLAS and OSM stops
DISTANCE_PROBLEM_THRESHOLD_M = 25  # meters

# ============================================================================
# ATTRIBUTES PROBLEM CONFIGURATION
# ============================================================================

# Enable/disable specific attribute checks
ENABLE_OPERATOR_MISMATCH_CHECK = True
ENABLE_NAME_MISMATCH_CHECK = True
ENABLE_UIC_MISMATCH_CHECK = True
ENABLE_LOCAL_REF_MISMATCH_CHECK = True

# ============================================================================
# MATCHING DISTANCE LIMITS
# ============================================================================

# Maximum distance for distance-based matching stages
DISTANCE_MATCHING_MAX_DISTANCE_M = 50  # meters

# Minimum distance for conflict resolution in distance matching
DISTANCE_MATCHING_MIN_SEPARATION_M = 10  # meters

# Minimum ratio for distance-based conflict resolution
DISTANCE_MATCHING_MIN_RATIO = 4.0  # closest must be 4x closer than second-closest


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_isolation_radius() -> int:
    """Get the isolation check radius in meters."""
    return ISOLATION_CHECK_RADIUS_M

def get_distance_problem_threshold() -> int:
    """Get the distance problem threshold in meters.""" 
    return DISTANCE_PROBLEM_THRESHOLD_M

def validate_config() -> bool:
    """Validate that all configuration values are sensible."""
    if ISOLATION_CHECK_RADIUS_M <= 0:
        raise ValueError("ISOLATION_CHECK_RADIUS_M must be positive")
    if DISTANCE_PROBLEM_THRESHOLD_M <= 0:
        raise ValueError("DISTANCE_PROBLEM_THRESHOLD_M must be positive")
    return True

# Validate configuration on import
validate_config()
