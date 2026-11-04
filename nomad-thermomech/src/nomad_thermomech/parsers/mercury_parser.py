"""Parser for Mercury RT DIC exports (*.csv, header 'Frame ID;Absolute Timestamp;...').

The Mercury export is often collected on another PC and added to the test folder later.
When it arrives, the test entry of the folder (created from TestNNN.log) gets the Mercury
file added and is reprocessed (synchronisation, DIC plots). If the WaveMatrix files are not
there yet, nothing happens; the WaveMatrix-log parser picks the export up when they arrive.
"""

from nomad.parsing import MatchingParser

from nomad_thermomech.parsers.common import find_logs, split_mainfile, upsert_test_entry
from nomad_thermomech.schema_packages.thermomech import MercuryExport


class MercuryExportParser(MatchingParser):
    def parse(self, mainfile, archive, logger=None, child_archives=None):
        folder_abs, folder_rel = split_mainfile(mainfile)
        archive.data = MercuryExport()
        tests = find_logs(folder_abs)
        if not tests:
            if logger:
                logger.info('no WaveMatrix test log in the folder yet; the export is added when it arrives')
            return
        if len(tests) > 1:
            if logger:
                logger.warning('several WaveMatrix tests in one folder - cannot assign the Mercury export',
                               tests=tests)
            return
        # only reprocess the test entry if this export was actually added to it
        archive.data.test_entry = upsert_test_entry(
            archive.m_context, folder_abs, folder_rel, tests[0], logger, reprocess_unchanged=False)
