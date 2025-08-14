import os
import re
import sys
import math
import pandas as pd


DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), 'data', 'processed'))
GTFS_PATH = os.path.join(DATA_DIR, 'atlas_routes_gtfs.csv')
HRDF_PATH = os.path.join(DATA_DIR, 'atlas_routes_hrdf.csv')


def normalize_route_id(route_id: str) -> str:
    if route_id is None or (isinstance(route_id, float) and math.isnan(route_id)):
        return None
    return re.sub(r'-j\d+', '-jXX', str(route_id))


def load_csv_safe(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"Failed to read CSV {path}: {e}")
        return None


def analyze_gtfs(df: pd.DataFrame) -> None:
    print("\n=== GTFS Analysis (atlas_routes_gtfs.csv) ===")
    required_cols = {'sloid', 'route_id', 'direction_id'}
    missing = required_cols - set(df.columns)
    if missing:
        print(f"Missing required cols in GTFS file: {missing}")
        return

    # Normalize route_id and direction_id
    df = df.copy()
    df['route_id_norm'] = df['route_id'].apply(normalize_route_id)
    # direction_id may be float/NaN; keep as string where available
    def _norm_dir(x):
        try:
            if pd.isna(x):
                return None
            return str(int(float(x)))
        except Exception:
            return None
    df['direction_id_norm'] = df['direction_id'].apply(_norm_dir)

    # 1) Average number of unique routes per sloid
    routes_per_sloid = (
        df.dropna(subset=['route_id_norm'])
          .groupby('sloid')['route_id_norm']
          .nunique()
    )
    # 2) Average number of unique (route,direction) per sloid
    rd_per_sloid = (
        df.dropna(subset=['route_id_norm'])
          .groupby('sloid')[['route_id_norm', 'direction_id_norm']]
          .apply(lambda g: g.drop_duplicates().shape[0])
    )

    if len(routes_per_sloid) == 0:
        print("No GTFS rows after normalization.")
        return

    print(f"SLOIDs with GTFS routes: {len(routes_per_sloid):,}")
    print(f"Average unique routes per SLOID (GTFS): {routes_per_sloid.mean():.2f}")
    print(f"Median unique routes per SLOID (GTFS): {routes_per_sloid.median():.2f}")
    print(f"Average unique (route,direction) per SLOID (GTFS): {rd_per_sloid.mean():.2f}")
    print(f"Median unique (route,direction) per SLOID (GTFS): {rd_per_sloid.median():.2f}")

    # 3) Multiplicity for same (sloid, route, direction)
    multiplicity = (
        df.dropna(subset=['route_id_norm'])
          .groupby(['sloid', 'route_id_norm', 'direction_id_norm'])
          .size()
          .reset_index(name='count')
    )
    dup_rows = multiplicity[multiplicity['count'] > 1].sort_values('count', ascending=False)
    total_groups = multiplicity.shape[0]
    dup_groups = dup_rows.shape[0]
    print(f"Groups (SLOID, route_norm, direction) total: {total_groups:,}")
    print(f"Groups with duplicates (>1 rows): {dup_groups:,} ({(dup_groups/total_groups*100 if total_groups else 0):.2f}%)")
    if not dup_rows.empty:
        print("Top examples of GTFS duplicate groups:")
        print(dup_rows.head(10).to_string(index=False))

    # 4) For each (route_norm, direction), how many distinct direction strings?
    if 'direction' in df.columns:
        dir_variety = (
            df.dropna(subset=['route_id_norm'])
              .groupby(['sloid', 'route_id_norm', 'direction_id_norm'])['direction']
              .nunique()
              .reset_index(name='unique_direction_strings')
        )
        inconsistent = dir_variety[dir_variety['unique_direction_strings'] > 1]
        print(f"(GTFS) Groups with >1 distinct direction string: {len(inconsistent):,}")
        if not inconsistent.empty:
            print(inconsistent.sort_values('unique_direction_strings', ascending=False).head(10).to_string(index=False))


def analyze_hrdf(df: pd.DataFrame) -> None:
    print("\n=== HRDF Analysis (atlas_routes_hrdf.csv) ===")
    required_cols = {'sloid', 'line_name', 'direction_name', 'direction_uic'}
    missing = required_cols - set(df.columns)
    if missing:
        print(f"Missing required cols in HRDF file: {missing}")
        return

    df = df.copy()
    # 1) Average number of unique lines per SLOID
    lines_per_sloid = df.groupby('sloid')['line_name'].nunique()
    print(f"SLOIDs with HRDF lines: {len(lines_per_sloid):,}")
    print(f"Average unique lines per SLOID (HRDF): {lines_per_sloid.mean():.2f}")
    print(f"Median unique lines per SLOID (HRDF): {lines_per_sloid.median():.2f}")

    # 2) For each (sloid, line_name), count unique direction_uic and direction_name
    dir_uic_per_pair = (
        df.groupby(['sloid', 'line_name'])['direction_uic']
          .nunique()
          .reset_index(name='unique_direction_uic_count')
    )
    dir_name_per_pair = (
        df.groupby(['sloid', 'line_name'])['direction_name']
          .nunique()
          .reset_index(name='unique_direction_name_count')
    )
    merged = pd.merge(dir_uic_per_pair, dir_name_per_pair, on=['sloid', 'line_name'], how='outer')
    print(f"Pairs (SLOID, line_name): {merged.shape[0]:,}")
    print(
        f"Average distinct direction_uic per (SLOID,line): {merged['unique_direction_uic_count'].mean():.2f}"
    )
    print(
        f"Average distinct direction_name per (SLOID,line): {merged['unique_direction_name_count'].mean():.2f}"
    )

    # 3) Show top multiplicity examples
    multi_uic = merged.sort_values('unique_direction_uic_count', ascending=False)
    multi_name = merged.sort_values('unique_direction_name_count', ascending=False)
    print("Top (SLOID,line) with many distinct direction_uic:")
    print(multi_uic.head(10).to_string(index=False))
    print("Top (SLOID,line) with many distinct direction_name:")
    print(multi_name.head(10).to_string(index=False))


def main():
    print(f"Looking for processed files under: {DATA_DIR}")
    gtfs_df = load_csv_safe(GTFS_PATH)
    hrdf_df = load_csv_safe(HRDF_PATH)

    if gtfs_df is None and hrdf_df is None:
        print("Neither GTFS nor HRDF processed files are available. Run the data generation first.")
        sys.exit(1)

    if gtfs_df is not None:
        analyze_gtfs(gtfs_df)
    else:
        print("Skipping GTFS analysis.")

    if hrdf_df is not None:
        analyze_hrdf(hrdf_df)
    else:
        print("Skipping HRDF analysis.")


if __name__ == '__main__':
    main()


