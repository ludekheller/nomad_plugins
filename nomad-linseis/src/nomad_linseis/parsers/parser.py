"""Parser for Linseis TMA text exports: for `<run>.txt` it creates the editable entry
`<run>.archive.json` (LinseisTMA, data_file = the export) unless it exists, and processes it."""

import json
import os

from nomad.parsing import MatchingParser

from nomad_linseis.schema_packages.tma import LinseisTMAExport

ELN_DEF = 'nomad_linseis.schema_packages.tma.LinseisTMA'


class LinseisTMAParser(MatchingParser):
    def parse(self, mainfile, archive, logger=None, child_archives=None):
        rel = mainfile.rsplit('/raw/', 1)[-1] if '/raw/' in mainfile else os.path.basename(mainfile)
        eln_rel = os.path.splitext(rel)[0] + '.archive.json'
        context = archive.m_context
        archive.data = LinseisTMAExport(tma_entry=eln_rel)
        if not context.raw_path_exists(eln_rel):
            with context.raw_file(eln_rel, 'w') as f:
                json.dump({'data': {'m_def': ELN_DEF, 'data_file': rel}}, f, indent=2)
            if logger:
                logger.info('created TMA entry for Linseis export', eln_entry=eln_rel)
        try:
            context.process_updated_raw_file(eln_rel, allow_modify=True)
        except NotImplementedError:
            pass  # local processing
