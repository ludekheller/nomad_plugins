#!/usr/bin/env python3
"""CSV of the DSC results of a NOMAD project or folder; see nomad_dsc_trios/results_table.py.

    python dsc_results_csv.py PROJECT_ID [--folder FOLDER] [-o results.csv] [--url ...]
"""

import sys
from pathlib import Path

try:
    from nomad_dsc_trios.results_table import main
except ImportError:  # run from the repository without installing the plugin (needs only requests)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'nomad_dsc_trios'))
    from results_table import main

if __name__ == '__main__':
    sys.exit(main())
