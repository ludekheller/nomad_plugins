"""Shared logic of the WaveMatrix-log and Mercury-export parsers.

One test = one folder. The editable test entry is <folder>/<TestNNN>[__<Mercury name>].archive.json.
Both parsers call `upsert_test_entry`: it collects the files of the test in the folder and
creates the entry, or - if the entry already exists (e.g. the WaveMatrix files were uploaded
first and the Mercury export later) - adds the missing files to it, keeping everything
entered by hand, and reprocesses it.
"""

import json
import os
import re

from nomad_thermomech.readers import is_mercury_export

ELN_DEF = 'nomad_thermomech.schema_packages.thermomech.ThermomechTest'
LOG_MARK = '60101,Log File Created'
WM_FILES = {
    'wavematrix_specimen': '.specimen.txt',
    'wavematrix_trends': '.steps.trends.csv',
    'wavematrix_method': '.itr_wma',
    'wavematrix_results': '.im_gpf',
}


def first_lines(path, n=1):
    try:
        with open(path, encoding='utf-8-sig', errors='replace') as f:
            return ''.join(f.readline() for _ in range(n))
    except OSError:
        return ''


def split_mainfile(mainfile):
    """(absolute folder, folder relative to the upload's raw root)."""
    rel_root = mainfile.rsplit('/raw/', 1)[-1] if '/raw/' in mainfile else os.path.basename(mainfile)
    return os.path.dirname(mainfile), os.path.dirname(rel_root)


def find_logs(folder_abs):
    """WaveMatrix test logs (TestNNN.log) in the folder -> list of test names."""
    return sorted(n[: -len('.log')] for n in os.listdir(folder_abs)
                  if n.endswith('.log') and LOG_MARK in first_lines(os.path.join(folder_abs, n), 5))


def find_mercury(folder_abs, test):
    return [n for n in sorted(os.listdir(folder_abs))
            if n.lower().endswith('.csv') and not n.startswith(test + '.')
            and is_mercury_export(first_lines(os.path.join(folder_abs, n)))]


def mercury_label(mercury_name):
    return re.sub(r'_export$', '', os.path.splitext(mercury_name)[0])


def collect_files(folder_abs, rel, test, logger=None):
    names = set(os.listdir(folder_abs))
    files = {'wavematrix_log': rel(test + '.log')}
    for key, suffix in WM_FILES.items():
        if test + suffix in names:
            files[key] = rel(test + suffix)
    for data in (test + '.Stop.csv', test + '.steps.tracking.csv'):
        if data in names:
            files['wavematrix_data'] = rel(data)
            break
    mercury = find_mercury(folder_abs, test)
    if mercury:
        files['mercury_export'] = rel(mercury[0])
        if len(mercury) > 1 and logger:
            logger.warning('several Mercury exports in the folder - using the first', used=mercury[0], all=mercury)
    return files, (mercury[0] if mercury else None)


def existing_entry(folder_abs, test):
    """Name of the test entry already in the folder (TestNNN.archive.json or TestNNN__*.archive.json)."""
    found = sorted(n for n in os.listdir(folder_abs)
                   if n == test + '.archive.json' or (n.startswith(test + '__') and n.endswith('.archive.json')))
    return found[0] if found else None


def upsert_test_entry(context, folder_abs, folder_rel, test, logger=None, reprocess_unchanged=True):
    """Create or update the test entry; returns its upload-relative path."""
    rel = lambda name: os.path.join(folder_rel, name) if folder_rel else name  # noqa: E731
    files, mercury = collect_files(folder_abs, rel, test, logger)
    full_name = test + ('__' + mercury_label(mercury) if mercury else '')

    entry = existing_entry(folder_abs, test)
    changed = False
    if entry is None:
        eln_rel = rel(full_name + '.archive.json')
        doc = {'data': {'m_def': ELN_DEF, 'name': full_name, 'files': files}}
        changed = True
        if logger:
            logger.info('created thermomechanical-test entry', eln_entry=eln_rel, files=files)
    else:
        eln_rel = rel(entry)
        with context.raw_file(eln_rel, 'r') as f:
            doc = json.load(f)
        data = doc.setdefault('data', {})
        data.setdefault('m_def', ELN_DEF)
        have = data.setdefault('files', {})
        added = {k: v for k, v in files.items() if not have.get(k)}
        if added:
            have.update(added)
            changed = True
            if logger:
                logger.info('added files to the thermomechanical-test entry', eln_entry=eln_rel, added=added)
        if data.get('name') in (None, '', test) and full_name != test:
            data['name'] = full_name  # default name -> include the Mercury name; hand-set names stay
            changed = True

    if changed:
        with context.raw_file(eln_rel, 'w') as f:
            json.dump(doc, f, indent=2)
    if changed or reprocess_unchanged:
        try:
            context.process_updated_raw_file(eln_rel, allow_modify=True)
        except NotImplementedError:
            pass  # local `nomad parse`
        except Exception as e:
            if logger:
                logger.warning('could not process the test entry', eln_entry=eln_rel, exc_info=e)
    return eln_rel
