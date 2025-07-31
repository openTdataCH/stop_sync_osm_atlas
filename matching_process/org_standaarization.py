import pandas as pd
import os

# Memoization cache for the normalization map
_normalization_map = None

def _get_normalization_map():
    """
    Loads the operator normalization map from the CSV file.
    Caches the map in memory after the first read.
    """
    global _normalization_map
    if _normalization_map is not None:
        return _normalization_map

    # The path to the CSV file is relative to this script's location
    # This makes it robust to where the main script is run from
    dir_path = os.path.dirname(os.path.realpath(__file__))
    csv_path = os.path.join(dir_path, 'operator_normalizations.csv')
    
    try:
        df = pd.read_csv(csv_path)
        # The map is a dictionary from 'alias' to 'standard_name'
        _normalization_map = pd.Series(df.standard_name.values, index=df.alias).to_dict()
    except FileNotFoundError:
        print(f"Warning: operator_normalizations.csv not found at {csv_path}. No operator standardization will be applied.")
        _normalization_map = {} # Avoid trying to load again
        
    return _normalization_map


def standardize_operator(operator):
    """
    Standardize operator names based on a mapping from a CSV file.
    
    Returns a tuple: (standardized_name, was_changed_boolean)
    """
    if not operator:
        return operator, False

    normalization_map = _get_normalization_map()
    
    # Check if the operator is in our normalization map
    standard_name = normalization_map.get(operator)
    
    if standard_name:
        return standard_name, True # A value was found in the map, so it was changed
    else:
        # Special handling for cases that are not simple mappings
        # These could also be moved to the CSV if more complex rules are not needed
        lower_op = operator.lower()
        if lower_op == "tpf":
            return "TPF Auto", True
        elif lower_op == "afa":
            return "AFA", True
        elif operator == "VBZ/DBZ": # This was missing from my previous logic but in original
            return "VBZ", True
            
    return operator, False # No change was made