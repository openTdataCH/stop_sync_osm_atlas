#!/usr/bin/env python3
"""
Recount data/stats.json from the published tables, and rebuild the statistics PDF.

It recounts the summary, the problems and the per-source sections exactly as
the import does, without the bundle. The sections that only the bundle holds,
the matches per rule and the unmatched analysis, keep the values of the last
import.
"""

import logging
import os
import sys

# Ensure the root directory is in the path
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)

from backend.importing.session import session
from backend.services.stats_export import (
    load_stats_from_file,
    recount_from_database,
    save_stats_to_file,
    generate_stats_summary_pdf,
)
from backend.app import create_app

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def main():
    logger.info("Recounting statistics from the database...")
    try:
        stats = recount_from_database(load_stats_from_file() or {}, session)
        filepath = save_stats_to_file(stats)
        logger.info("Updated statistics at %s", filepath)

        summary = stats['summary']
        logger.info("Summary: %s matched pairs (%s%%)", summary['matched_pairs'], summary['match_rate_percent'])
        logger.info("OSM coverage: %s%% of ATLAS has nearby OSM", summary['atlas_with_osm_within_50m_percent'])

        app = create_app()
        with app.app_context():
            logger.info("Generated the PDF summary at %s", generate_stats_summary_pdf(stats))
    except Exception:
        logger.exception("Failed to regenerate stats")
        sys.exit(1)
    finally:
        session.close()


if __name__ == "__main__":
    main()
