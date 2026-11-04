"""Parser for Instron WaveMatrix test logs (TestNNN.log).

Creates (or updates) the editable test entry of the folder, see `common.upsert_test_entry`.
"""

import os

from nomad.parsing import MatchingParser

from nomad_thermomech.parsers.common import split_mainfile, upsert_test_entry
from nomad_thermomech.schema_packages.thermomech import WaveMatrixTestLog


class WaveMatrixTestParser(MatchingParser):
    def parse(self, mainfile, archive, logger=None, child_archives=None):
        folder_abs, folder_rel = split_mainfile(mainfile)
        test = os.path.basename(mainfile)[: -len('.log')]
        eln_rel = upsert_test_entry(archive.m_context, folder_abs, folder_rel, test, logger)
        archive.data = WaveMatrixTestLog(test_entry=eln_rel)
