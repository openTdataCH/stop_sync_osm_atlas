"""Geospatial utilities for Swiss border filtering."""
import os
import json
import pandas as pd

try:
    import geopandas as gpd  # type: ignore
    from shapely.geometry import Polygon, MultiPolygon, shape  # type: ignore
    from shapely.ops import unary_union  # type: ignore
    _HAS_GPD = True
except Exception:
    gpd = None  # type: ignore
    Polygon = None  # type: ignore
    MultiPolygon = None  # type: ignore
    shape = None  # type: ignore
    unary_union = None  # type: ignore
    _HAS_GPD = False

_SWISS_POLYGON = None  # cached shapely geometry (MultiPolygon)

def _ensure_swiss_geojson_cache(geojson_path: str) -> None:
    """Ensure the Switzerland GeoJSON cache exists at geojson_path.

    Downloads from SWISS_GEOJSON_URL if missing.
    """
    import requests
    
    if os.path.exists(geojson_path):
        return
    url_default = "https://raw.githubusercontent.com/ZHB/switzerland-geojson/master/country/switzerland.geojson"
    url = os.getenv("SWISS_GEOJSON_URL", url_default)
    os.makedirs(os.path.dirname(geojson_path), exist_ok=True)
    try:
        print(f"Downloading Switzerland boundary GeoJSON from {url} …")
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        with open(geojson_path, "wb") as f:
            f.write(resp.content)
        print(f"Saved Switzerland boundary to {geojson_path}")
    except Exception as exc:
        raise RuntimeError(f"Failed to download Switzerland GeoJSON from {url}: {exc}")

def _load_swiss_polygon():
    """Load precise Switzerland polygon from cached GeoJSON.

    Returns shapely (Multi)Polygon. Raises if cache is missing or invalid.
    """
    global _SWISS_POLYGON
    if _SWISS_POLYGON is not None:
        return _SWISS_POLYGON
    if not _HAS_GPD:
        raise RuntimeError("GeoPandas is required for Swiss border filtering. Please install geopandas and shapely.")

    osm_cache_file = os.getenv('SWISS_GEOJSON_PATH', "data/raw/switzerland.geojson")
    if not os.path.exists(osm_cache_file):
        # Attempt to fetch automatically if missing
        _ensure_swiss_geojson_cache(osm_cache_file)

    try:
        print("Loading Switzerland boundary from cache…")
        with open(osm_cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        geom_union = None
        if isinstance(data, dict):
            t = data.get("type")
            if t == "FeatureCollection":
                geoms = []
                for feature in data.get("features", []):
                    geom_obj = feature.get("geometry") if isinstance(feature, dict) else None
                    if geom_obj:
                        geoms.append(shape(geom_obj))
                if not geoms:
                    raise RuntimeError("No geometries found in FeatureCollection")
                geom_union = geoms[0] if len(geoms) == 1 else unary_union(geoms)
            elif t == "Feature":
                geom_obj = data.get("geometry")
                if not geom_obj:
                    raise RuntimeError("Feature has no geometry")
                geom_union = shape(geom_obj)
            elif t in ("Polygon", "MultiPolygon", "GeometryCollection"):
                geom_union = shape(data)
            else:
                raise RuntimeError(f"Unsupported GeoJSON type: {t}")
        else:
            raise RuntimeError("Invalid GeoJSON content")

        if not isinstance(geom_union, (Polygon, MultiPolygon)):
            raise RuntimeError(f"Unexpected geometry type for Switzerland boundary: {type(geom_union)}")

        _SWISS_POLYGON = geom_union
        print("Successfully loaded Switzerland boundary from cache")
        return _SWISS_POLYGON
    except Exception as exc:
        try:
            if gpd is None:
                raise RuntimeError(str(exc))
            print("GeoJSON parse failed, attempting GeoPandas read as fallback…")
            swiss_gdf = gpd.read_file(osm_cache_file)
            if len(swiss_gdf) == 0:
                raise RuntimeError("Empty Switzerland boundary data")
            try:
                geom_union = swiss_gdf.geometry.union_all()
            except Exception:
                geom_union = swiss_gdf.unary_union
            if isinstance(geom_union, (Polygon, MultiPolygon)):
                _SWISS_POLYGON = geom_union
                print("Successfully loaded Switzerland boundary via GeoPandas fallback")
                return _SWISS_POLYGON
            raise RuntimeError(f"Unexpected geometry type for Switzerland boundary: {type(geom_union)}")
        except Exception as exc2:
            raise RuntimeError(f"Failed to load Switzerland boundary from cache: {exc2}")

def filter_points_in_switzerland(df: pd.DataFrame, lat_col: str, lon_col: str) -> pd.DataFrame:
    """Filter rows whose WGS84 coordinates lie inside Switzerland using the precise OSM polygon."""
    # Basic cleanup
    df = df.dropna(subset=[lat_col, lon_col]).copy()
    df[lat_col] = pd.to_numeric(df[lat_col], errors='coerce')
    df[lon_col] = pd.to_numeric(df[lon_col], errors='coerce')
    df = df.dropna(subset=[lat_col, lon_col])

    before = len(df)
    if before == 0:
        return pd.DataFrame(columns=df.columns)

    swiss_poly = _load_swiss_polygon()
    # Cheap bounding-box prefilter to reduce the number of points that GeoPandas needs to test.
    # This preserves exact semantics because we still do the precise polygon test afterwards.
    try:
        minx, miny, maxx, maxy = swiss_poly.bounds  # (lon_min, lat_min, lon_max, lat_max)
        df = df[
            df[lon_col].between(minx, maxx, inclusive='both') &
            df[lat_col].between(miny, maxy, inclusive='both')
        ].copy()
    except Exception:
        # If bounds fail for any reason, fall back to the full dataset
        pass

    bbox_filtered = len(df)
    if bbox_filtered == 0:
        print(f"Swiss filter: bbox prefilter kept 0 (from {before:,} total)")
        return pd.DataFrame(columns=df.columns)

    # Accurate point-in-polygon on full dataset
    try:
        gdf = gpd.GeoDataFrame(
            df,
            geometry=gpd.points_from_xy(df[lon_col], df[lat_col], crs='EPSG:4326'),
        )
        # Keep points inside Switzerland or exactly on the border
        inside_or_border = gdf.intersects(swiss_poly)
        filtered = gdf[inside_or_border].drop(columns='geometry')
        
        print(f"Swiss filter: filter kept {len(filtered):,} (from {before:,} total; bbox prefilter kept {bbox_filtered:,})")
        return pd.DataFrame(filtered)
    except Exception as exc:
        raise RuntimeError(f"Swiss polygon containment failed: {exc}")
