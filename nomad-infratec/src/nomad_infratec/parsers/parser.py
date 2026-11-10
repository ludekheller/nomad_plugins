"""Parser for InfraTec IR records (.tdms, written by the LabVIEW acquisition): for `<name>.tdms`
it creates the editable entry `<name>.archive.json` (IRRecord, data_file = the .tdms) unless it
exists, and processes it. The `.tdms_index` next to it is not needed."""

import json
import os

from nomad.parsing import MatchingParser

from nomad_infratec.schema_packages.ir import IRRawFile

ELN_DEF = 'nomad_infratec.schema_packages.ir.IRRecord'


class IRRecordParser(MatchingParser):
    def parse(self, mainfile, archive, logger=None, child_archives=None):
        rel = mainfile.rsplit('/raw/', 1)[-1] if '/raw/' in mainfile else os.path.basename(mainfile)
        eln_rel = os.path.splitext(rel)[0] + '.archive.json'
        context = archive.m_context
        archive.data = IRRawFile(ir_entry=eln_rel)
        if not context.raw_path_exists(eln_rel):
            name = os.path.splitext(os.path.basename(rel))[0]
            with context.raw_file(eln_rel, 'w') as f:
                json.dump({'data': {'m_def': ELN_DEF, 'data_file': rel, 'name': name}}, f, indent=2)
            if logger:
                logger.info('created IR record entry', eln_entry=eln_rel)
        try:
            context.process_updated_raw_file(eln_rel, allow_modify=True)
        except NotImplementedError:
            pass  # local processing
