"""Parser for TRIOS DSC CSV exports.

For an uploaded `<run>.csv` it creates the editable entry `<run>.archive.json`
(DSC_SMA, data_file = the CSV) unless that file already exists. That entry reads the
CSV when it is processed. The CSV itself becomes a small read-only entry pointing to it.
"""

import json
import os

from nomad.parsing import MatchingParser

from nomad_dsc_trios.schema_packages.dsc import TRIOS_DSC_Export

ELN_DEF = 'nomad_dsc_trios.schema_packages.dsc.DSC_SMA'


class TriosDSCParser(MatchingParser):
    def parse(self, mainfile, archive, logger=None, child_archives=None):
        csv_rel = mainfile.rsplit('/raw/', 1)[-1] if '/raw/' in mainfile else os.path.basename(mainfile)
        eln_rel = os.path.splitext(csv_rel)[0] + '.archive.json'

        archive.data = TRIOS_DSC_Export(dsc_entry=eln_rel)
        context = archive.m_context
        if context.raw_path_exists(eln_rel):
            # entry exists (e.g. CSV re-uploaded): reprocess it so it re-reads the CSV
            self._reprocess(context, eln_rel, logger)
            return

        with context.raw_file(eln_rel, 'w') as f:
            json.dump({'data': {'m_def': ELN_DEF, 'data_file': csv_rel}}, f, indent=2)
        if logger:
            logger.info('created DSC entry for TRIOS export', eln_entry=eln_rel)
        self._reprocess(context, eln_rel, logger)

    @staticmethod
    def _reprocess(context, path, logger):
        try:
            context.process_updated_raw_file(path, allow_modify=True)
        except NotImplementedError:
            pass  # local `nomad parse`: no upload to process
        except Exception as e:
            if logger:
                logger.warning('could not process the DSC entry', eln_entry=path, exc_info=e)
