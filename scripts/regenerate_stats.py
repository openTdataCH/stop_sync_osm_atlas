#!/usr/bin/env python3
"""
Regenerate statistics from the database.

This script queries the current state of the import database and updates
data/stats.json with the latest summary and problem counts. It is useful
for refreshing the dashboard after database changes without rerunning
 the full matching pipeline.
"""

import os
import sys
import logging

# Ensure the root directory is in the path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from matching_and_import_db.database.session import session
from backend.services.stats_export import (
    load_stats_from_file,
    save_stats_to_file,
    compute_summary_from_db,
    compute_db_stats,
    generate_stats_summary_pdf
)
from backend.app import create_app

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("Regenerating statistics from database...")
    
    try:
        # 1. Load existing stats to preserve non-DB metrics (like matching stages if they existed)
        stats = load_stats_from_file()
        if not stats:
            logger.info("No existing stats.json found, creating new structure.")
            stats = {"version": "1.0", "generated_at": ""}

        # 2. Update summary from DB
        logger.info("Computing high-level summary...")
        stats['summary'] = compute_summary_from_db(session)
        
        # 3. Update problem stats from DB
        logger.info("Computing problem statistics...")
        stats['problems'] = compute_db_stats(session)
        
        # 4. Save back to file
        import datetime
        stats['generated_at'] = datetime.datetime.utcnow().isoformat() + "Z"
        
        filepath = save_stats_to_file(stats)
        logger.info(f"Successfully updated statistics at {filepath}")
        
        # Print summary
        s = stats['summary']
        logger.info(f"Summary: {s['matched_pairs']} matched pairs ({s['match_rate_percent']}%)")
        logger.info(f"OSM coverage: {s['atlas_with_osm_within_50m_percent']}% of ATLAS has nearby OSM")
        
        # 5. Generate PDF report
        logger.info("Generating PDF summary report...")
        app = create_app()
        with app.app_context():
            pdf_path = generate_stats_summary_pdf(stats)
            logger.info(f"Successfully generated PDF report at {pdf_path}")
        
    except Exception as e:
        logger.error(f"Failed to regenerate stats: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        session.close()

if __name__ == "__main__":
    main()
