"""Parser for Instron WaveMatrix test logs (TestNNN.log).

One test = one folder. For TestNNN.log the parser looks for the other WaveMatrix files
(TestNNN.*) and a Mercury RT export (*.csv starting with 'Frame ID;Absolute Timestamp')
in the same folder, and creates the editable entry
    <folder>/<TestNNN>__<Mercury export name>.archive.json      (or <TestNNN>.archive.json)
which reads the files when it is processed.
"""

import json
import os
import re

from nomad.parsing import MatchingParser

from nomad_thermomech.readers import is_mercury_export
from nomad_thermomech.schema_packages.thermomech import WaveMatrixTestLog

ELN_DEF = 'nomad_thermomech.schema_packages.thermomech.ThermomechTest'
WM_FILES = {
    'wavematrix_specimen': '.specimen.txt',
    'wavematrix_trends': '.steps.trends.csv',
    'wavematrix_method': '.itr_wma',
    'wavematrix_results': '.im_gpf',
}


def _first_line(path):
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            return f.readline()
    except OSError:
        return ''


class WaveMatrixTestParser(MatchingParser):
    def parse(self, mainfile, archive, logger=None, child_archives=None):
        folder_abs = os.path.dirname(mainfile)
        rel_root = mainfile.rsplit('/raw/', 1)[-1] if '/raw/' in mainfile else os.path.basename(mainfile)
        folder_rel = os.path.dirname(rel_root)
        rel = lambda name: os.path.join(folder_rel, name) if folder_rel else name  # noqa: E731
        test = os.path.basename(mainfile)[: -len('.log')]
        names = sorted(os.listdir(folder_abs))

        files = {'wavematrix_log': rel(os.path.basename(mainfile))}
        for key, suffix in WM_FILES.items():
            if test + suffix in names:
                files[key] = rel(test + suffix)
        for data in (test + '.Stop.csv', test + '.steps.tracking.csv'):
            if data in names:
                files['wavematrix_data'] = rel(data)
                break
        mercury = [n for n in names if n.lower().endswith('.csv') and not n.startswith(test + '.')
                   and is_mercury_export(_first_line(os.path.join(folder_abs, n)))]
        if mercury:
            files['mercury_export'] = rel(mercury[0])
            if len(mercury) > 1 and logger:
                logger.warning('several Mercury exports in the folder - using the first', used=mercury[0], all=mercury)

        name = test
        if mercury:
            name += '__' + re.sub(r'_export$', '', os.path.splitext(mercury[0])[0])
        eln_rel = rel(name + '.archive.json')
        archive.data = WaveMatrixTestLog(test_entry=eln_rel)

        context = archive.m_context
        if not context.raw_path_exists(eln_rel):
            with context.raw_file(eln_rel, 'w') as f:
                json.dump({'data': {'m_def': ELN_DEF, 'name': name, 'files': files}}, f, indent=2)
            if logger:
                logger.info('created thermomechanical-test entry', eln_entry=eln_rel, files=files)
        try:
            context.process_updated_raw_file(eln_rel, allow_modify=True)
        except NotImplementedError:
            pass  # local `nomad parse`
        except Exception as e:
            if logger:
                logger.warning('could not process the test entry', eln_entry=eln_rel, exc_info=e)
