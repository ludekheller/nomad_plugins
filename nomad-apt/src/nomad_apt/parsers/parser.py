"""Parser for APT files. One editable entry per reconstruction file, `<file stem>.archive.json`
in the same folder. The reconstruction file is the only file needed; all others are optional
and are added to the entry when they are (or later get) uploaded:

  reconstruction  .apt / .epos / .pos  (required; same stem in several formats: .epos > .apt > .pos)
  experiment      AP Suite export .xml listing the reconstruction (by its id = .apt file name):
                  gives the reconstruction name (entry title), run header and the raw file
  raw             .hits / .rhit / .rraw named in the .xml, or with the run number of the entry
  range           .rrng / .rng: the range file whose name starts with the reconstruction name
                  (longest match wins), otherwise one of the same run, otherwise the only one
                  in the folder if its name has no (other) run number

Links and values entered by hand are kept.
"""

import json
import os
import re

from nomad.parsing import MatchingParser

from nomad_apt.readers import RECON_EXT, RUN_RE, kind, read_experiment_xml, run_key
from nomad_apt.schema_packages.apt import APTRawFile

ELN_DEF = 'nomad_apt.schema_packages.apt.APTMeasurement'


def _split(mainfile):
    rel = mainfile.rsplit('/raw/', 1)[-1] if '/raw/' in mainfile else os.path.basename(mainfile)
    return os.path.dirname(mainfile), os.path.dirname(rel)


def _safe(name):
    return re.sub(r'[^\w.+-]+', '_', name).strip('_') or 'apt_run'


def plan(folder_abs, logger=None):
    """-> {entry key (reconstruction file stem): {quantity: file name or value}} for the folder."""
    names = sorted(os.listdir(folder_abs))
    lower = {n.lower(): n for n in names}
    stem = lambda n: os.path.splitext(n)[0]  # noqa: E731

    exported = {}  # reconstruction id (lower) -> (name, xml file, raw file)
    for x in [n for n in names if n.lower().endswith('.xml')]:
        try:
            exp = read_experiment_xml(os.path.join(folder_abs, x))
        except Exception:  # not an AP Suite export  # noqa: BLE001
            continue
        raw = lower.get((exp['raw_file'] or '').lower())
        for r in exp['reconstructions']:
            if r['id']:
                exported[r['id'].lower()] = (r['name'] or r['id'], x, raw)

    entries, titles = {}, {}
    order = list(RECON_EXT)
    for n in names:
        if kind(n) != 'reconstruction':
            continue
        key = _safe(stem(n))
        old = entries.get(key, {}).get('reconstruction_file')
        if old and order.index(os.path.splitext(n)[1].lower()) >= order.index(os.path.splitext(old)[1].lower()):
            continue
        e = entries.setdefault(key, {})
        e['reconstruction_file'] = n
        title, xml, raw = exported.get(stem(n).lower(), (stem(n), None, None))
        titles[key] = title
        if xml:
            e.update(experiment_file=xml, reconstruction_id=stem(n))
        if not raw:
            run = run_key(title)
            raw = next((r for r in names if kind(r) == 'raw' and run_key(r) == run), None)
        if raw:
            e['raw_file'] = raw

    # range files: longest reconstruction name that starts the range file name, else same run, else single
    ranges = [n for n in names if kind(n) == 'range']
    owner = {}
    for rf in ranges:
        hits = [k for k, t in titles.items() if stem(rf).lower().startswith(t.lower())]
        if hits:
            owner.setdefault(max(hits, key=lambda k: len(titles[k])), []).append(rf)
    for k, e in entries.items():
        if owner.get(k):
            e['range_file'] = owner[k][0]
            continue
        same_run = [rf for rf in ranges if run_key(rf) == run_key(titles[k])]
        single = ranges if len(ranges) == 1 and not RUN_RE.search(ranges[0]) else []  # not of another run
        if same_run or single:
            e['range_file'] = (same_run or single)[0]
    for k, e in entries.items():
        e['_title'] = titles[k]
    return entries


def upsert_entry(context, folder_rel, name, files, logger=None):
    rel = lambda n: os.path.join(folder_rel, n) if folder_rel else n  # noqa: E731
    title = files.pop('_title', name)
    files = {k: (rel(v) if k.endswith('_file') else v) for k, v in files.items()}
    eln_rel = rel(name + '.archive.json')
    if not context.raw_path_exists(eln_rel):
        doc = {'data': {'m_def': ELN_DEF, 'name': title, 'run_number': run_key(title), **files}}
        changed = True
    else:
        with context.raw_file(eln_rel, 'r') as f:
            doc = json.load(f)
        data = doc.setdefault('data', {})
        added = {k: v for k, v in files.items() if not data.get(k)}
        data.update(added)
        changed = bool(added)
    if changed:
        with context.raw_file(eln_rel, 'w') as f:
            json.dump(doc, f, indent=2)
        if logger:
            logger.info('APT measurement entry written', eln_entry=eln_rel, files=files)
        try:
            context.process_updated_raw_file(eln_rel, allow_modify=True)
        except NotImplementedError:
            pass  # local processing
        except Exception as e:
            if logger:
                logger.warning('could not process the APT entry', eln_entry=eln_rel, exc_info=e)
    return eln_rel


class APTParser(MatchingParser):
    def parse(self, mainfile, archive, logger=None, child_archives=None):
        folder_abs, folder_rel = _split(mainfile)
        name = os.path.basename(mainfile)
        archive.data = APTRawFile(file_kind=kind(name) or 'experiment', run=run_key(name))
        mine = {n: e for n, e in plan(folder_abs, logger).items() if name in e.values()}
        if not mine and logger:
            logger.info('no reconstruction file (.apt/.epos/.pos) for this file in the folder yet', file=name)
        archive.data.apt_entry = ', '.join(
            upsert_entry(archive.m_context, folder_rel, n, e, logger) for n, e in sorted(mine.items())) or None
