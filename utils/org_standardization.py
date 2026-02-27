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

    dir_path = os.path.dirname(os.path.realpath(__file__))
    csv_path = os.path.join(dir_path, 'operator_normalizations.csv')
    try:
        df = pd.read_csv(csv_path, dtype=str)
        df['alias'] = df['alias'].astype(str).str.strip()
        df['standard_name'] = df['standard_name'].astype(str).str.strip()
        df = df.dropna(subset=['alias', 'standard_name'])
        _normalization_map = pd.Series(df.standard_name.values, index=df.alias).to_dict()
    except FileNotFoundError:
        print(f"Warning: operator_normalizations.csv not found at {csv_path}. No operator standardization will be applied.")
        _normalization_map = {}
    return _normalization_map


def standardize_operator(operator):
    """
    Standardize operator names based on a mapping from a CSV file.
    Returns a tuple: (standardized_name, was_changed_boolean)
    """
    if operator is None:
        return operator, False
    operator_stripped = str(operator).strip()
    if operator_stripped == "":
        return operator, False
    normalization_map = _get_normalization_map()
    standard_name = normalization_map.get(operator_stripped)
    if standard_name:
        return standard_name, True
    return operator_stripped, False


