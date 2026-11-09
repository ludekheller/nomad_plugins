"""Parsers for the Walter+Bai (UTTRMO) machine record and its 1D DIC export.

The machine record `<name>` (no extension) creates the editable test entry
`<name>.archive.json` in the same folder, with `<name>_dic.csv` if present. A DIC export
uploaded later is added to the existing entry, which is then reprocessed. Values entered
by hand in the entry are kept.
"""

import json
import os

from nomad.parsing import MatchingParser

from nomad_walterbai.schema_packages.walterbai import WalterBaiRawFile

ELN_DEF = 'nomad_walterbai.schema_packages.walterbai.WalterBaiTest'
DIC_SUFFIX = '_dic.csv'


def _split(mainfile):
    rel = mainfile.rsplit('/raw/', 1)[-1] if '/raw/' in mainfile else os.path.basename(mainfile)
    return os.path.dirname(mainfile), os.path.dirname(rel)


def upsert_entry(context, folder_abs, folder_rel, name, logger=None, reprocess_unchanged=True):
    rel = lambda n: os.path.join(folder_rel, n) if folder_rel else n  # noqa: E731
    files = {'machine_file': rel(name)}
    if os.path.exists(os.path.join(folder_abs, name + DIC_SUFFIX)):
        files['dic_file'] = rel(name + DIC_SUFFIX)
    eln_rel = rel(name + '.archive.json')
    changed = False
    if not context.raw_path_exists(eln_rel):
        doc = {'data': {'m_def': ELN_DEF, 'name': name, 'files': files}}
        changed = True
    else:
        with context.raw_file(eln_rel, 'r') as f:
            doc = json.load(f)
        have = doc.setdefault('data', {}).setdefault('files', {})
        added = {k: v for k, v in files.items() if not have.get(k)}
        if added:
            have.update(added)
            changed = True
    if changed:
        with context.raw_file(eln_rel, 'w') as f:
            json.dump(doc, f, indent=2)
        if logger:
            logger.info('Walter+Bai test entry written', eln_entry=eln_rel, files=files)
    if changed or reprocess_unchanged:
        try:
            context.process_updated_raw_file(eln_rel, allow_modify=True)
        except NotImplementedError:
            pass  # local processing
        except Exception as e:
            if logger:
                logger.warning('could not process the test entry', eln_entry=eln_rel, exc_info=e)
    return eln_rel


class WalterBaiParser(MatchingParser):
    def parse(self, mainfile, archive, logger=None, child_archives=None):
        folder_abs, folder_rel = _split(mainfile)
        name = os.path.basename(mainfile)
        archive.data = WalterBaiRawFile(
            test_entry=upsert_entry(archive.m_context, folder_abs, folder_rel, name, logger))


class WalterBaiDICParser(MatchingParser):
    def parse(self, mainfile, archive, logger=None, child_archives=None):
        folder_abs, folder_rel = _split(mainfile)
        name = os.path.basename(mainfile)[: -len(DIC_SUFFIX)]
        archive.data = WalterBaiRawFile()
        if not os.path.exists(os.path.join(folder_abs, name)):
            if logger:
                logger.info('machine record not in the folder yet; the DIC export is added when it arrives')
            return
        archive.data.test_entry = upsert_entry(archive.m_context, folder_abs, folder_rel, name, logger,
                                               reprocess_unchanged=False)
