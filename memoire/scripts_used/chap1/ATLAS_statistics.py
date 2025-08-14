#!/usr/bin/env python3
"""
ATLAS Statistics Calculator

This script computes comprehensive statistics for the ATLAS dataset to verify the 
statistics mentioned in the thesis document, particularly focusing on the 
"Entrées identifiables par (number, designation) seul" metric.

METHODOLOGY FOR IDENTIFIABILITY:

1. **Identifiable by `number` alone**: 
   - Entries where the UIC `number` appears exactly once in the dataset
   - These entries don't need `designation` for unique identification

2. **Identifiable by (`number`, `designation`) combination**:
   - Entries where the UIC `number` appears multiple times (so number alone is insufficient)
   - The entry has a non-empty `designation` 
   - The (`number`, `designation`) combination is unique within the dataset

3. **Total identifiable entries**:
   - Sum of categories 1 and 2 above
   - This represents all ATLAS entries that can be uniquely identified

4. **Non-identifiable entries**:
   - Entries with non-unique `number` AND no `designation`
   - Entries with non-unique `number` AND non-unique (`number`, `designation`) combination

Author: Generated for thesis verification
"""

import os
import pandas as pd
import numpy as np
from collections import Counter

def main():
    """Compute comprehensive ATLAS statistics."""
    
    # File paths
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    atlas_path = os.path.join(root, 'data', 'raw', 'stops_ATLAS.csv')
    
    if not os.path.exists(atlas_path):
        print(f"Error: ATLAS file not found at {atlas_path}")
        return
    
    print("Loading ATLAS data...")
    df = pd.read_csv(atlas_path, sep=';')
    
    print("=" * 60)
    print("ATLAS DATASET STATISTICS")
    print("=" * 60)
    
    # Basic counts
    total_entries = len(df)
    print(f"Total entries in dataset: {total_entries:,}")
    
    # 1. Entries with coordinates (WGS84)
    has_coords = df.dropna(subset=['wgs84North', 'wgs84East'])
    coords_count = len(has_coords)
    print(f"Entries with coordinates (WGS84): {coords_count:,}")
    
    # 2. BOARDING_PLATFORM entries
    if 'trafficPointElementType' in df.columns:
        boarding_platform_count = len(df[df['trafficPointElementType'] == 'BOARDING_PLATFORM'])
        print(f"BOARDING_PLATFORM entries: {boarding_platform_count:,}")
    
    # 3. Distinct UIC numbers
    if 'number' in df.columns:
        # Filter out null/empty numbers
        valid_numbers = df[pd.notna(df['number']) & (df['number'] != '')]
        distinct_uic_count = valid_numbers['number'].nunique()
        print(f"Distinct UIC numbers: {distinct_uic_count:,}")
    
    print("\n" + "=" * 60)
    print("DESIGNATION ANALYSIS")
    print("=" * 60)
    
    # 4. Designation analysis
    if 'designation' in df.columns:
        # Non-empty designations
        non_empty_designation = df[pd.notna(df['designation']) & (df['designation'] != '')]
        non_empty_count = len(non_empty_designation)
        distinct_designations = non_empty_designation['designation'].nunique()
        print(f"Non-empty designations: {non_empty_count:,} ({distinct_designations} distinct values)")
        
        # Missing designations
        missing_designation = df[pd.isna(df['designation']) | (df['designation'] == '')]
        missing_count = len(missing_designation)
        print(f"Missing designations: {missing_count:,}")
        
        # Show top 10 most common designations
        if not non_empty_designation.empty:
            top_designations = non_empty_designation['designation'].value_counts().head(10)
            print(f"\nTop 10 most common designations:")
            for i, (designation, count) in enumerate(top_designations.items(), 1):
                print(f"  {i:2d}. '{designation}': {count:,} entries")
    
    print("\n" + "=" * 60)
    print("IDENTIFIABILITY ANALYSIS")
    print("=" * 60)
    
    # Key analysis: Identifiability
    if 'number' in df.columns and 'designation' in df.columns:
        
        # Create clean copies for analysis
        df_clean = df.copy()
        
        # Clean number field - convert to string and handle nulls
        df_clean['number_clean'] = df_clean['number'].apply(
            lambda x: str(int(x)) if pd.notna(x) and x != '' else None
        )
        
        # Clean designation field
        df_clean['designation_clean'] = df_clean['designation'].apply(
            lambda x: str(x).strip() if pd.notna(x) and x != '' else None
        )
        
        # Filter to entries with valid numbers
        df_with_number = df_clean[pd.notna(df_clean['number_clean'])]
        print(f"Entries with valid number: {len(df_with_number):,}")
        
        # Analyze number uniqueness
        number_counts = df_with_number['number_clean'].value_counts()
        unique_numbers = number_counts[number_counts == 1]
        print(f"Numbers that appear only once: {len(unique_numbers):,}")
        print(f"Numbers that appear multiple times: {len(number_counts) - len(unique_numbers):,}")
        
        # Case where number alone is sufficient (unique number)
        entries_unique_by_number = df_with_number[
            df_with_number['number_clean'].isin(unique_numbers.index)
        ]
        unique_by_number_count = len(entries_unique_by_number)
        print(f"Entries uniquely identifiable by number alone: {unique_by_number_count:,}")
        
        # Among unique numbers, how many have missing designation?
        unique_missing_designation = entries_unique_by_number[
            pd.isna(entries_unique_by_number['designation_clean'])
        ]
        unique_missing_des_count = len(unique_missing_designation)
        print(f"  - Among these, entries with missing designation: {unique_missing_des_count:,}")
        
        # Now the key metric: entries identifiable by (number, designation) combination
        # CORRECT LOGIC: We only need (number, designation) when the number appears multiple times
        
        # First, identify numbers that appear multiple times (non-unique numbers)
        non_unique_numbers = number_counts[number_counts > 1].index
        
        # For entries with non-unique numbers, check if they have designations
        df_non_unique_numbers = df_with_number[df_with_number['number_clean'].isin(non_unique_numbers)]
        df_with_both = df_non_unique_numbers[pd.notna(df_non_unique_numbers['designation_clean'])]
        
        # Create (number, designation) combinations for these entries
        df_with_both = df_with_both.copy()  # Avoid SettingWithCopyWarning
        df_with_both['number_designation'] = (
            df_with_both['number_clean'].astype(str) + '|' + 
            df_with_both['designation_clean'].astype(str)
        )
        
        # Count occurrences of each (number, designation) combination
        combination_counts = df_with_both['number_designation'].value_counts()
        unique_combinations = combination_counts[combination_counts == 1]
        
        # These are entries identifiable by (number, designation) where number alone is insufficient
        entries_identifiable_by_combo = df_with_both[
            df_with_both['number_designation'].isin(unique_combinations.index)
        ]
        
        identifiable_by_combo_count = len(entries_identifiable_by_combo)
        
        print(f"\n*** KEY STATISTIC ***")
        print(f"Entries identifiable by (number, designation) alone: {identifiable_by_combo_count:,}")
        print(f"(These are entries where number appears multiple times but the (number, designation) combination is unique)")
        
        # Verification: Check that we're only counting entries where number is non-unique
        print(f"\n--- Verification ---")
        print(f"Entries with non-unique numbers: {len(df_non_unique_numbers):,}")
        print(f"Among these, entries with designation: {len(df_with_both):,}")
        print(f"Unique (number, designation) combinations among non-unique numbers: {len(unique_combinations):,}")
        print(f"Final count (identifiable by combo): {identifiable_by_combo_count:,}")
        
        # Additional analysis: entries with non-unique numbers but NO designation
        df_non_unique_no_designation = df_non_unique_numbers[pd.isna(df_non_unique_numbers['designation_clean'])]
        non_unique_no_des_count = len(df_non_unique_no_designation)
        print(f"Entries with non-unique numbers but NO designation: {non_unique_no_des_count:,}")
        print(f"  (These entries cannot be uniquely identified)")
        
        # Total identifiability calculation
        # Total = unique by number + unique by (number, designation) where number is not unique
        total_identifiable = unique_by_number_count + identifiable_by_combo_count
        print(f"\nTotal identifiable by number + (designation or uniqueness of number): {total_identifiable:,}")
        
        print(f"\n--- DETAILED BREAKDOWN ---")
        print(f"1. Identifiable by number alone (unique number): {unique_by_number_count:,}")
        print(f"   - With designation: {unique_by_number_count - unique_missing_des_count:,}")
        print(f"   - Without designation: {unique_missing_des_count:,}")
        print(f"2. Identifiable by (number, designation) where number is NOT unique: {identifiable_by_combo_count:,}")
        print(f"3. Non-identifiable (non-unique number, no designation): {non_unique_no_des_count:,}")
        print(f"4. Total identifiable (1 + 2): {total_identifiable:,}")
        print(f"5. Total entries: {len(df_with_number):,}")
        print(f"6. Verification: {total_identifiable:,} + {non_unique_no_des_count:,} + [duplicates] = {len(df_with_number):,}")
        
        # Analysis of the 4,499 mentioned in thesis
        print(f"\n--- MISSING DESIGNATION ANALYSIS ---")
        print(f"From thesis: '4,499 cases where the unique entry of number is without designation'")
        print(f"Our calculation: {unique_missing_des_count:,}")
        
        if unique_missing_des_count != 4499:
            print(f"⚠️  Discrepancy found! Expected 4,499, got {unique_missing_des_count:,}")
        else:
            print(f"✓ Matches thesis value")
        
        # Check the main statistic
        print(f"\n--- Main statistic verification ---")
        print(f"From thesis: 'Entrées identifiables par (number, designation) seul: 10,928'")
        print(f"Our calculation: {identifiable_by_combo_count:,}")
        
        if identifiable_by_combo_count != 10928:
            print(f"⚠️  DISCREPANCY FOUND! Expected 10,928, got {identifiable_by_combo_count:,}")
            print(f"   Difference: {identifiable_by_combo_count - 10928:,}")
        else:
            print(f"✓ Matches thesis value")
    
    print("\n" + "=" * 60)
    print("SUMMARY OF FINDINGS")
    print("=" * 60)
    
    # Print a summary comparison with thesis values
    thesis_values = {
        "Lignes avec coordonnées": 56510,
        "BOARDING_PLATFORM": 55818,
        "UIC distincts": 27225,
        "designation non vides": 11462,
        "designation manquantes": 44356,
        "Identifiables par (number, designation) seul": 10928,
        "Total identifiables": 15427
    }
    
    our_values = {
        "Lignes avec coordonnées": coords_count,
        "BOARDING_PLATFORM": boarding_platform_count if 'trafficPointElementType' in df.columns else "N/A",
        "UIC distincts": distinct_uic_count if 'number' in df.columns else "N/A",
        "designation non vides": non_empty_count if 'designation' in df.columns else "N/A",
        "designation manquantes": missing_count if 'designation' in df.columns else "N/A",
        "Identifiables par (number, designation) seul": identifiable_by_combo_count if 'number' in df.columns and 'designation' in df.columns else "N/A",
        "Total identifiables": total_identifiable if 'number' in df.columns and 'designation' in df.columns else "N/A"
    }
    
    print("Statistic comparison:")
    print(f"{'Metric':<45} {'Thesis':<10} {'Our calc':<10} {'Match':<8}")
    print("-" * 73)
    
    for metric in thesis_values.keys():
        thesis_val = thesis_values[metric]
        our_val = our_values[metric]
        
        if our_val == "N/A":
            match_status = "N/A"
        else:
            match_status = "✓" if our_val == thesis_val else "✗"
        
        print(f"{metric:<45} {thesis_val:<10,} {our_val if our_val == 'N/A' else f'{our_val:,}':<10} {match_status:<8}")

if __name__ == '__main__':
    main()
