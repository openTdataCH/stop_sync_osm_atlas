# Persistent Data Management System

The Persistent Data Management system is designed to preserve manually validated solutions and notes across data imports. This unified system handles both problem solutions and contextual notes for ATLAS stops and OSM nodes. Here we explain the approach, its implementation, benefits, challenges, and how various scenarios are handled.

## Problem Statement

Stop data can be regularly updated through imports from ATLAS and OSM. During these imports, the system detects various problems (distance issues, unmatched stops, attribute mismatches, duplicates) that require human validation. Without a persistent solution system, these validations would be lost on each new import, requiring users to repeatedly solve the same problems.

Additionally, notes added to ATLAS stops and OSM nodes provide valuable context that should be preserved across imports.

## Implementation

### Database Structure

The system uses a single table to manage both persistent solutions and notes:

**`persistent_data` table**: Permanent storage for validated solutions and notes
- `id`: Primary key
- `sloid`: ATLAS stop ID (can be NULL for OSM-only stops)
- `osm_node_id`: OSM node ID (can be NULL for ATLAS-only stops)
- `problem_type`: Type of problem ('distance', 'unmatched', 'attributes', 'duplicates') or NULL for notes
- `solution`: The validated solution text (for problems)
- `note_type`: Type of note ('atlas', 'osm') or NULL for problem solutions
- `note`: The note text (for ATLAS or OSM notes)
- `created_at` / `updated_at`: Timestamps for tracking

The table has a unique constraint on (`sloid`, `osm_node_id`, `problem_type`, `note_type`) to ensure there's only one entry per combination.

### Process Flow

1. **Data Import**:
   - All existing data is deleted (including the `problems` table)
   - New data is imported and problems are detected
   - The `persistent_data` table remains untouched

2. **Solution Application**:
   - After import, the system queries all persistent solutions and notes
   - For each solution, it finds matching stops in the new data by `sloid` or `osm_node_id`
   - If a matching stop has the same type of problem, the persistent solution is applied
   - For notes, it applies them to matching stops/nodes that still exist in the new data

3. **User Interaction**:
   - Users can solve problems in the UI as before
   - Solutions are saved to the `problems` table
   - Users can choose to make solutions persistent, which saves them to the `persistent_data` table
   - Similarly, users can add notes to ATLAS stops and OSM nodes and choose to make them persistent
   - The UI indicates which solutions and notes are persistent

4. **Management**:
   - A dedicated interface allows users to view and manage persistent solutions and notes
   - Solutions and notes can be filtered by type and deleted if needed

## Handling Data Changes

### For Problem Solutions

#### Scenario 1: Stop Exists with Same Problem
- **Example**: A distance problem between ATLAS stop A and OSM node B was solved as "OSM correct"
- **Outcome**: The persistent solution "OSM correct" is automatically applied to the new problem

#### Scenario 2: Stop Exists but Problem Resolved
- **Example**: A distance problem between ATLAS stop A and OSM node B was previously solved, but in the new data, the coordinates have been fixed
- **Outcome**: No problem is detected, so no solution needs to be applied
- **Handling**: The system logs that the problem no longer exists but retains the persistent solution for future imports

#### Scenario 3: Stop No Longer Exists
- **Example**: An ATLAS stop that had a persistent solution has been removed from the dataset
- **Outcome**: No matching stop is found, so no solution is applied
- **Handling**: The system logs that no matching stop was found but retains the persistent solution in case the stop reappears in future imports

#### Scenario 4: New Problem Type for Existing Stop
- **Example**: A stop previously had a distance problem with a persistent solution, and now also has an attributes problem
- **Outcome**: The persistent solution is applied to the distance problem, but the attributes problem remains unsolved
- **Handling**: The user needs to solve the new problem type and can choose to make that solution persistent as well

### For Notes

#### Scenario 1: Stop Exists
- **Example**: An ATLAS stop has a persistent note and still exists in the new data
- **Outcome**: The persistent note is automatically applied to the stop

#### Scenario 2: Stop No Longer Exists
- **Example**: An ATLAS stop that had a persistent note has been removed from the dataset
- **Outcome**: No matching stop is found, so no note is applied
- **Handling**: The system logs that no matching stop was found but retains the persistent note in case the stop reappears in future imports

## Benefits

1. Eliminates the need to repeatedly solve the same problems
2. Preserves knowledge about why certain decisions were made
3. Solutions can be updated or deleted even if they already are on the permanent table
4. Uses natural keys to match solutions to problems, even as internal IDs change
5. Preserves valuable context notes for stops and nodes across data imports

## Challenges and Limitations

1. A solution that was valid for a problem in one data import might not be appropriate for a similar problem in a later import if the stops data has changed significatly.
2. The system requires periodic review of persistent solutions to ensure they remain valid
3. The dual-table approach adds complexity to the codebase
4. Notes are always applied the corresponding stops regardless of coordinate or attribute changes, which could lead to notes being applied to stops that have moved/changed significantly.

## Best Practices

1. Review persistent solutions to ensure they remain valid
2. When making a solution persistent, consider adding context about why this solution was chosen
3. Keep an eye on the number of skipped persistent solutions during imports, as this may indicate data drift
4. Only make notes persistent if they contain valuable information that should be preserved across imports. Periodically review them to ensure they're still relevant to the stops they're attached to

## Key Components

1. **Database Schema**: Unified `persistent_data` table for solutions and notes with proper indexing and constraints
2. **API Endpoints**:
   - `/api/save_solution`: Save a temporary solution (not persistent by default)
   - `/api/make_solution_persistent`: Make an existing solution persistent
   - `/api/check_persistent_solution`: Check if a solution is persistent
   - `/api/save_note/atlas` and `/api/save_note/osm`: Save notes with optional persistence flag
   - `/api/make_note_persistent/atlas` and `/api/make_note_persistent/osm`: Make existing notes persistent
   - `/api/check_persistent_note/atlas` and `/api/check_persistent_note/osm`: Check if notes are persistent
   - `/api/persistent_data`: List and manage persistent solutions and notes with pagination and filtering
   - `/api/non_persistent_data`: List non-persistent solutions and notes with optimized SQL queries
   - `/api/make_all_persistent`: Batch operation to make all non-persistent data persistent
3. **Import Process**: Automated function to apply persistent solutions and notes after data import
4. **UI Components**: 
   - Dual-tab interface for persistent vs. non-persistent data management
   - Consistent rendering with clear visual indicators
   - Batch operations for efficiency
   - Robust error handling and user feedback


## Conclusion

The Persistent Data Management system provides a robust and efficient way to preserve human validation and context across data imports. With the recent improvements, it now offers:
- Better performance through optimized database queries
- Consistent and intuitive user interface 
- Complete API coverage for all operations
- Enhanced error handling and user feedback
- Clear separation between persistent and temporary data

The system maintains the core benefits of efficiency and consistency across data imports while providing a significantly improved user experience.