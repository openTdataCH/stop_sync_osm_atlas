"""
Match record type definitions and factory functions.

This module provides a standardized way to create match dictionaries
used throughout the matching pipeline, eliminating duplicate match
dictionary construction code across multiple files.

Usage:
    from matching_and_import_db.utils.match_record import create_match_record, extract_atlas_fields
    
    match = create_match_record(
        sloid=atlas_entry['sloid'],
        csv_lat=csv_lat,
        csv_lon=csv_lon,
        osm_node=osm_node,
        distance_m=dist,
        match_type='exact',
        matching_notes="Matched by UIC reference",
        number=atlas_entry['number'],
        **extract_atlas_fields(atlas_entry),
    )
"""
from typing import TypedDict, Optional, Any, Dict
import pandas as pd


class MatchRecord(TypedDict, total=False):
    """
    Type definition for match records used throughout the pipeline.
    
    This provides IDE support and documentation for the ~20 fields
    used in match dictionaries across exact_matching, distance_matching,
    and matching_script modules.
    """
    # ATLAS fields
    sloid: str
    number: Optional[str]
    uic_ref: Optional[str]
    csv_designation: str
    csv_designation_official: str
    csv_lat: float
    csv_lon: float
    csv_business_org_abbr: str
    
    # OSM fields
    osm_node_id: str
    osm_lat: Optional[float]
    osm_lon: Optional[float]
    osm_local_ref: Optional[str]
    osm_network: str
    osm_operator: str
    osm_amenity: str
    osm_railway: str
    osm_aerialway: str
    osm_name: str
    osm_uic_name: str
    osm_uic_ref: str
    osm_public_transport: str
    
    # Match metadata
    distance_m: Optional[float]
    match_type: str
    matching_notes: str


def create_match_record(
    *,
    sloid: str,
    csv_lat: float,
    csv_lon: float,
    osm_node: Optional[Dict[str, Any]],
    distance_m: Optional[float],
    match_type: str,
    matching_notes: str,
    # Optional ATLAS fields
    number: Optional[str] = None,
    uic_ref: Optional[str] = None,
    csv_designation: str = "",
    csv_designation_official: str = "",
    csv_business_org_abbr: str = "",
) -> MatchRecord:
    """
    Factory function to create a standardized match record.
    
    This centralizes the ~20-field match dictionary construction that was
    previously duplicated in 5+ locations across the codebase.
    
    Args:
        sloid: ATLAS stop SLOID (required)
        csv_lat: ATLAS latitude (required)
        csv_lon: ATLAS longitude (required)
        osm_node: OSM node dictionary with 'node_id', 'lat', 'lon', 'tags', 'local_ref'
                  Can be None for unmatched entries.
        distance_m: Distance between ATLAS and OSM points in meters
        match_type: Type of match (e.g., 'exact', 'distance_matching_2')
        matching_notes: Human-readable notes about the match
        number: ATLAS UIC number
        uic_ref: UIC reference (defaults to number if not provided)
        csv_designation: ATLAS designation
        csv_designation_official: ATLAS official designation
        csv_business_org_abbr: Business organization abbreviation

    Returns:
        MatchRecord dictionary with all standard fields populated
        
    Example:
        >>> osm_node = {'node_id': '123', 'lat': 47.0, 'lon': 8.0, 'tags': {'name': 'Test'}}
        >>> match = create_match_record(
        ...     sloid='ch:1:sloid:123',
        ...     csv_lat=47.001,
        ...     csv_lon=8.001,
        ...     osm_node=osm_node,
        ...     distance_m=15.5,
        ...     match_type='exact',
        ...     matching_notes='Matched by UIC',
        ... )
    """
    # Handle None osm_node gracefully
    if osm_node is None:
        osm_node = {}
    
    tags = osm_node.get('tags', {}) if isinstance(osm_node.get('tags'), dict) else {}
    
    return MatchRecord(
        # ATLAS fields
        sloid=sloid,
        number=number,
        uic_ref=uic_ref if uic_ref else (str(number) if number else None),
        csv_designation=csv_designation,
        csv_designation_official=csv_designation_official or csv_designation,
        csv_lat=csv_lat,
        csv_lon=csv_lon,
        csv_business_org_abbr=csv_business_org_abbr,
        # OSM fields
        osm_node_id=osm_node.get('node_id', '') if osm_node else '',
        osm_lat=osm_node.get('lat') if osm_node else None,
        osm_lon=osm_node.get('lon') if osm_node else None,
        osm_local_ref=osm_node.get('local_ref', '') if osm_node else '',
        osm_network=tags.get('network', ''),
        osm_operator=tags.get('operator', ''),
        osm_amenity=tags.get('amenity', ''),
        osm_railway=tags.get('railway', ''),
        osm_aerialway=tags.get('aerialway', ''),
        osm_name=tags.get('name', ''),
        osm_uic_name=tags.get('uic_name', ''),
        osm_uic_ref=tags.get('uic_ref', ''),
        osm_public_transport=tags.get('public_transport', ''),
        # Match metadata
        distance_m=distance_m,
        match_type=match_type,
        matching_notes=matching_notes,
    )


def extract_atlas_fields(row: Dict[str, Any], pd_notna=None) -> Dict[str, str]:
    """
    Extract standardized ATLAS fields from a DataFrame row or dict.
    
    This helper extracts the common ATLAS fields (designation, designation_official,
    business_org_abbr) with proper null handling and string conversion.
    
    Args:
        row: Dictionary or DataFrame row containing ATLAS data
        pd_notna: Optional pandas.notna function for null checking.
                  If None, uses pd.notna.
                  
    Returns:
        Dictionary with keys: csv_designation, csv_designation_official, csv_business_org_abbr
        
    Example:
        >>> atlas_entry = {'designation': 'Test', 'designationOfficial': 'Test Official'}
        >>> fields = extract_atlas_fields(atlas_entry)
        >>> # Returns {'csv_designation': 'Test', 'csv_designation_official': 'Test Official', 'csv_business_org_abbr': ''}
    """
    if pd_notna is None:
        pd_notna = pd.notna
    
    designation = str(row.get('designation', '')).strip() if pd_notna(row.get('designation')) else ""
    designation_official = str(row.get('designationOfficial', '')).strip() if pd_notna(row.get('designationOfficial')) else designation
    business_org_abbr = str(row.get('servicePointBusinessOrganisationAbbreviationEn', '') or '').strip()
    
    return {
        'csv_designation': designation,
        'csv_designation_official': designation_official,
        'csv_business_org_abbr': business_org_abbr,
    }
