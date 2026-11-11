"""Parser for TRIOS exports: DSC (CSV, JSON) and DMA (JSON).

For an uploaded `<run>.csv`, `<run>.json`, `<run>.json.gz` or `<run>.gz` it creates the editable entry
`<run>.archive.json` (DSC_SMA or DMA_TRIOS by the instrument type in the export,
data_file = the export) unless that file already exists. That entry reads the export when
it is processed. The export itself becomes a small read-only entry pointing to it.
"""

import gzip
import json
import os
import re

from nomad.parsing import MatchingParser

from nomad_dsc_trios.schema_packages.dsc import TRIOS_DSC_Export

ELN_DEF = 'nomad_dsc_trios.schema_packages.dsc.DSC_SMA'
DMA_DEF = 'nomad_dsc_trios.schema_packages.dma.DMA_TRIOS'
SETTINGS_DEF = 'nomad_dsc_trios.schema_packages.dsc.DSC_EvaluationSettings'


def instrument_type(path):
    """Instrument type of a TRIOS JSON export ('DSC2500', 'DMA850' ...) from the first 300 kB."""
    opener = gzip.open if path.lower().endswith('.gz') else open
    try:
        with opener(path, 'rt', encoding='utf-8-sig', errors='replace') as f:
            head = f.read(300_000)
    except OSError:
        return None
    m = re.search(r'"InstrumentConfigurations"\s*:\s*\[\s*\{.*?"Type"\s*:\s*"([^"]+)"', head, re.S)
    return m.group(1) if m else None


class TriosDSCParser(MatchingParser):
    def parse(self, mainfile, archive, logger=None, child_archives=None):
        csv_rel = mainfile.rsplit('/raw/', 1)[-1] if '/raw/' in mainfile else os.path.basename(mainfile)
        eln_rel = re.sub(r'\.(csv|json\.gz|json|gz)$', '', csv_rel, flags=re.IGNORECASE) + '.archive.json'

        archive.data = TRIOS_DSC_Export(dsc_entry=eln_rel)
        context = archive.m_context
        if context.raw_path_exists(eln_rel):
            # entry exists (e.g. CSV re-uploaded): reprocess it so it re-reads the CSV;
            # folder settings deleted meanwhile are created again (DSC only)
            try:
                with context.raw_file(eln_rel, 'r') as f:
                    is_dsc = str(json.load(f).get('data', {}).get('m_def', '')) == ELN_DEF
            except (OSError, ValueError):
                is_dsc = False
            if is_dsc:
                from nomad_dsc_trios.evaluation_nomad import create_default_settings  # noqa: PLC0415

                create_default_settings(context, os.path.dirname(csv_rel), SETTINGS_DEF, logger)
            self._reprocess(context, eln_rel, logger)
            return

        m_def = ELN_DEF
        if not csv_rel.lower().endswith('.csv') and (instrument_type(mainfile) or '').upper().startswith('DMA'):
            m_def = DMA_DEF
        with context.raw_file(eln_rel, 'w') as f:
            json.dump({'data': {'m_def': m_def, 'data_file': csv_rel}}, f, indent=2)
        if logger:
            logger.info('created entry for TRIOS export', eln_entry=eln_rel, entry_type=m_def.rsplit('.', 1)[-1])
        if m_def == ELN_DEF:  # first DSC curve of a folder: editable evaluation settings (mode off)
            from nomad_dsc_trios.evaluation_nomad import create_default_settings  # noqa: PLC0415

            create_default_settings(context, os.path.dirname(csv_rel), SETTINGS_DEF, logger)
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
