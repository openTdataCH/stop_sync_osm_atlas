import requests
import zipfile
import io
import pandas as pd

def get_atlas_stops(output_path, download_url):
    """Download and process ATLAS stops data."""
    response = requests.get(download_url)
    response.raise_for_status()
    
    print("ATLAS: download successful, extracting ZIP file…")
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        csv_files = z.namelist()
        print("ATLAS: files in ZIP:", csv_files)
        
        if not csv_files:
            raise Exception("No CSV file found in the ZIP archive.")
        
        csv_filename = csv_files[0]
        print("ATLAS: extracting:", csv_filename)

        with z.open(csv_filename) as f:
            # Load and filter for Switzerland (country code 85) with coordinates
            df = pd.read_csv(f, sep=";")
            df = df[df['uicCountryCode'] == 85]

            # Save processed data (Swiss BOARDING_PLATFORM rows with coordinates and future validTo)
            df.to_csv(output_path, sep=";", index=False)
            
            # Print statistics
            print(f"ATLAS: total BOARDING_PLATFORM rows kept = {len(df):,}")
            print(f"ATLAS: processed CSV saved to: {output_path}")

if __name__ == "__main__":
    atlas_stops_csv_output_path = "data/raw/stops_ATLAS.csv"
    download_url = "https://data.opentransportdata.swiss/en/dataset/traffic-points-actual-date/permalink"
    get_atlas_stops(atlas_stops_csv_output_path, download_url)
