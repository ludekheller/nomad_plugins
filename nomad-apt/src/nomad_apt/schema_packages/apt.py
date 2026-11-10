"""Atom probe tomography (CAMECA LEAP ...) run.

One entry per run (e.g. R6043_00349). It links the files of the run:
  raw_file             .hits / .rhit / .rraw  - CAMECA raw data (closed format: only recorded)
  reconstruction_file  .epos / .pos / .apt    - exported from AP Suite / IVAS
  range_file           .rrng / .rng
On processing the entry reads the reconstruction and range file (when present) and builds:
mass spectrum (log scale, ranges shaded), composition (ions and elements), a 3-D view of a
random sample of ions, composition profile vs depth, 2-D element maps (x-y, x-depth), mass
spectrum vs depth, ions per depth slice, an explorer of the depth profile, and where the file
has them the voltage history and the detector hit map.
AP Suite experiment exports (.xml next to the .apt files) also give the reconstruction name,
comments and the run header (specimen, date, run comments with temperature, laser energy,
detection rate ...; instrument). Other acquisition and reconstruction parameters are typed
in by hand. Values typed in by hand are never overwritten.
"""

import os

import numpy as np
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import Datetime, MEnum, Quantity, SchemaPackage, Section, SubSection

from nomad_apt.figures import atomic_percent, build_figures
from nomad_apt.readers import analyse, open_ions, read_experiment_xml, read_ranges, run_info, run_key

m_package = SchemaPackage(name='Atom probe tomography (APT)')

INSTRUMENTS = ['CAMECA LEAP 4000X HR', 'CAMECA LEAP 4000X Si', 'CAMECA LEAP 5000 XR', 'CAMECA LEAP 5000 XS',
               'CAMECA LEAP 6000 XR', 'CAMECA EIKOS', 'CAMECA Invizo 6000', 'other']
TIME_ZONE = 'Europe/Prague'


def _str(rich=False, **kw):
    comp = 'RichTextEditQuantity' if rich else 'StringEditQuantity'
    return Quantity(type=str, a_eln=ELNAnnotation(component=comp), **kw)


def _num(unit=None, **kw):
    return Quantity(type=np.float64, unit=unit, a_eln=ELNAnnotation(component='NumberEditQuantity'), **kw)


def _local(iso):
    """Naive time from AP Suite (local time of the instrument PC) -> aware, Europe/Prague."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    dt = datetime.fromisoformat(iso)
    return (dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(TIME_ZONE))).isoformat()


def _file(desc):
    return Quantity(type=str, description=desc, a_eln=ELNAnnotation(component='FileEditQuantity'),
                    a_browser=dict(adaptor='RawFileAdaptor'))


class APTSpecimen(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    specimen_id = _str()
    material = _str(description='e.g. NiTi, NiTiHf, NiTiNb')
    nominal_composition = _str()
    preparation = Quantity(type=MEnum('FIB lift-out', 'electropolishing', 'other'),
                           a_eln=ELNAnnotation(component='EnumEditQuantity'))
    region_of_interest = _str(description='e.g. grain boundary, precipitate, matrix')
    processing_history = _str(rich=True, description='heat treatment, ageing ...')


class APTAcquisition(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    pulse_mode = Quantity(type=MEnum('laser', 'voltage'), a_eln=ELNAnnotation(component='EnumEditQuantity'))
    laser_energy = _num('picojoule')
    laser_wavelength = _num('nanometer')
    pulse_fraction = _num(description='% (voltage pulsing)')
    pulse_frequency = _num('kilohertz')
    base_temperature = _num('kelvin')
    detection_rate = _num(description='% ions per pulse')
    chamber_pressure = _num('pascal')
    flight_path = _num('millimeter')
    start_voltage = _num('volt')
    run_comments = _str(rich=True, description='Comments of the run (from the run header of an AP Suite export)')
    run_outcome = _str(description='e.g. fractured, ended by operator')
    instrument_configuration = Quantity(type=str, description='Instrument components and serial numbers (run header)')
    run_header = Quantity(type=str, description='Readable text of the run header (AP Suite export), for reference')


class APTReconstruction(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    software = _str(description='e.g. AP Suite 6.3, IVAS 3.8')
    method = _str(description='e.g. voltage, tip profile')
    reconstruction_id = Quantity(type=str, description='AP Suite reconstruction id (= name of the exported .apt)')
    comments = _str(description='AP Suite reconstruction comments')
    created = Quantity(type=Datetime, description='Time the reconstruction was created')
    created_by = _str()
    creation_method = Quantity(type=str)
    field_factor_k = _num()
    image_compression_factor = _num()
    evaporation_field = _num('volt / nanometer')
    detector_efficiency = _num(description='fraction, e.g. 0.37 or 0.52')
    notes = _str(rich=True)


class APTRangedIon(ArchiveSection):
    m_def = Section(label_quantity='ion')
    ion = Quantity(type=str)
    composition = Quantity(type=str, description='e.g. Ni:1 Ti:1')
    mass_ranges = Quantity(type=str, description='low-high (Da), ...')
    counts = Quantity(type=np.int64)
    ionic_fraction = Quantity(type=np.float64, description='% of ranged ions')


class APTElement(ArchiveSection):
    m_def = Section(label_quantity='element')
    element = Quantity(type=str)
    atoms = Quantity(type=np.int64, description='atoms counted (molecular ions decomposed)')
    atomic_percent = Quantity(type=np.float64)
    error = Quantity(type=np.float64, description='counting statistics, 2σ (at.%)')


class APTProfileElement(ArchiveSection):
    m_def = Section(label_quantity='element')
    element = Quantity(type=str)
    atomic_percent = Quantity(type=np.float64, shape=['*'], description='at.% per depth slice (NaN: < 30 atoms)')
    error = Quantity(type=np.float64, shape=['*'], description='2σ counting error (at.%)')


class APTDepthProfile(ArchiveSection):
    m_def = Section(description='Composition vs depth from the top of the reconstruction, all ions')
    slice_width = Quantity(type=np.float64, unit='nanometer')
    depth = Quantity(type=np.float64, shape=['*'], unit='nanometer', description='Slice centres')
    ions = Quantity(type=np.int64, shape=['*'], description='Ions per slice')
    unranged = Quantity(type=np.int64, shape=['*'], description='Unranged ions per slice')
    elements = SubSection(section_def=APTProfileElement, repeats=True)


class APTResults(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    ions_reconstructed = Quantity(type=np.int64)
    ions_ranged = Quantity(type=np.int64)
    ranged_fraction = Quantity(type=np.float64, description='%')
    multiple_hit_fraction = Quantity(type=np.float64, description='% of ions in multiple-hit events (.epos)')
    voltage_start = Quantity(type=np.float64, unit='volt')
    voltage_end = Quantity(type=np.float64, unit='volt')
    x_range = Quantity(type=np.float64, unit='nanometer')
    y_range = Quantity(type=np.float64, unit='nanometer')
    z_depth = Quantity(type=np.float64, unit='nanometer')
    mass_bin_width = Quantity(type=np.float64, unit='dalton')
    mass_to_charge = Quantity(type=np.float64, shape=['*'], unit='dalton', description='Mass spectrum bin centres')
    counts = Quantity(type=np.int64, shape=['*'], description='Mass spectrum counts')
    ranged_ions = SubSection(section_def=APTRangedIon, repeats=True)
    composition = SubSection(section_def=APTElement, repeats=True)
    depth_profile = SubSection(section_def=APTDepthProfile)


class APTMeasurement(PlotSection, EntryData):
    """One atom probe run (raw file, reconstruction, range file)."""

    m_def = Section(label='APT measurement')

    name = _str(description='Run, e.g. R6043_00349')
    run_number = _str()
    instrument = Quantity(type=MEnum(*INSTRUMENTS), a_eln=ELNAnnotation(component='EnumEditQuantity'))
    operator = _str()
    measurement_date = Quantity(type=Datetime, a_eln=ELNAnnotation(component='DateTimeEditQuantity'))
    raw_file = _file('CAMECA raw data (.hits / .rhit / .rraw)')
    raw_file_size = Quantity(type=np.float64, unit='megabyte')
    reconstruction_file = _file('Reconstruction exported from AP Suite / IVAS (.epos / .pos / .apt)')
    range_file = _file('Range file (.rrng / .rng)')
    experiment_file = _file('AP Suite experiment export (.xml): run header and reconstruction list')
    reconstruction_id = Quantity(type=str, description='Reconstruction of the AP Suite export shown in this entry')
    description = _str(rich=True, description='Purpose of the run')
    notes = _str(rich=True)

    specimen = SubSection(section_def=APTSpecimen)
    acquisition = SubSection(section_def=APTAcquisition)
    reconstruction = SubSection(section_def=APTReconstruction)
    results = SubSection(section_def=APTResults)

    def normalize(self, archive, logger):
        for name, cls in (('specimen', APTSpecimen), ('acquisition', APTAcquisition),
                          ('reconstruction', APTReconstruction)):
            if getattr(self, name) is None:
                setattr(self, name, cls())
        if self.experiment_file:
            try:
                self._read_export(archive)
            except Exception as e:
                logger.warning('could not read the AP Suite export .xml', file=self.experiment_file, exc_info=e)
        if self.raw_file:
            try:
                with archive.m_context.raw_file(self.raw_file, 'rb') as f:
                    f.seek(0, 2)
                    self.raw_file_size = float(f"{f.tell() / 1e6:.4g}")
            except Exception as e:
                logger.warning('raw file not found', raw_file=self.raw_file, exc_info=e)
        if self.reconstruction_file:
            try:
                self._read(archive, logger)
            except Exception as e:
                logger.error('could not read the APT reconstruction', file=self.reconstruction_file, exc_info=e)
        if self.name and archive.metadata is not None:
            archive.metadata.entry_name = self.name
        super().normalize(archive, logger)

    def _read_export(self, archive):
        exp = read_experiment_xml(self._path(archive, self.experiment_file))
        recs = exp['reconstructions']
        rid = (self.reconstruction_id or '').lower()
        r = next((x for x in recs if (x['id'] or '').lower() == rid), recs[0] if len(recs) == 1 else None)
        if r is None:
            return
        rc = self.reconstruction
        stem = os.path.splitext(os.path.basename(self.reconstruction_file or ''))[0]
        if r.get('name') and (self.name is None or self.name == stem):  # title from AP Suite, unless typed in
            self.name = r['name']
            self.run_number = run_key(r['name'])
        for q, k in (('reconstruction_id', 'id'), ('comments', 'comments'), ('created_by', 'user'),
                     ('creation_method', 'method')):
            if getattr(rc, q) is None and r.get(k):
                setattr(rc, q, r[k])
        if rc.created is None and r.get('created'):
            rc.created = _local(r['created'][:26])
        if rc.software is None:
            rc.software = 'AP Suite'
        if not r.get('parameters'):
            return
        info = run_info(r['parameters'])
        acq, sp = self.acquisition, self.specimen
        if sp.specimen_id is None and info.get('specimen'):
            sp.specimen_id = info['specimen']
        if self.measurement_date is None and info.get('date'):
            self.measurement_date = _local(info['date'])
        if self.instrument is None and info.get('instrument'):
            self.instrument = info['instrument']
        for q, v in info['values'].items():
            if getattr(acq, q) is None:
                setattr(acq, q, v)
        if acq.pulse_mode is None and acq.laser_energy is not None:
            acq.pulse_mode = 'laser'
        for q, k in (('run_comments', 'comments'), ('run_outcome', 'outcome'),
                     ('instrument_configuration', 'configuration')):
            if getattr(acq, q) is None and info.get(k):
                setattr(acq, q, info[k] if q != 'run_comments' else info[k].replace('\n', '<br>'))
        acq.run_header = '\n'.join(info['header'])

    def _path(self, archive, rel):
        with archive.m_context.raw_file(rel, 'rb') as f:
            return f.name

    def _read(self, archive, logger):
        ranges = []
        if self.range_file:
            try:
                ranges = read_ranges(self._path(archive, self.range_file))
            except Exception as e:
                logger.warning('could not read the range file', range_file=self.range_file, exc_info=e)
        ions = open_ions(self._path(archive, self.reconstruction_file))
        a = analyse(ions, ranges)

        r = APTResults(ions_reconstructed=a['n_ions'], mass_bin_width=a['bin_width'],
                       mass_to_charge=a['mass'], counts=a['counts'],
                       x_range=float(np.subtract(*a['extent']['x'][::-1])),
                       y_range=float(np.subtract(*a['extent']['y'][::-1])), z_depth=a['extent']['depth'])
        if ranges:
            r.ions_ranged = a['n_ranged']
            r.ranged_fraction = round(100 * a['n_ranged'] / a['n_ions'], 3)
            tot = a['n_ranged'] or 1
            r.ranged_ions = [APTRangedIon(
                ion=ion, counts=c, ionic_fraction=round(100 * c / tot, 4),
                composition=' '.join(f'{el}:{k}' for el, k in a['ion_comp'][ion].items()),
                mass_ranges=', '.join(f'{lo:.3f}-{hi:.3f}' for lo, hi in a['ion_windows'][ion]))
                for ion, c in sorted(a['ion_counts'].items(), key=lambda kv: -kv[1])]
            atoms = sum(a['element_counts'].values()) or 1
            comp = []
            for el, c in sorted(a['element_counts'].items(), key=lambda kv: -kv[1]):
                p = c / atoms
                comp.append(APTElement(element=el, atoms=c, atomic_percent=round(100 * p, 4),
                                       error=round(200 * np.sqrt(p * (1 - p) / atoms), 4)))
            r.composition = comp
        if 'vdc' in a:
            r.voltage_start, r.voltage_end = float(a['vdc'][0]), float(a['vdc'][-1])
        if a.get('multiple_fraction') is not None:
            r.multiple_hit_fraction = round(100 * a['multiple_fraction'], 3)
        # acquisition channels stored in an .apt (medians over the run); hand values are kept
        ch, acq = a.get('channels') or {}, self.acquisition
        for q, k, f in (('base_temperature', 'temperature_K', 1), ('pulse_frequency', 'frequency_Hz', 1e-3),
                        ('detection_rate', 'detection_rate', 100), ('chamber_pressure', 'pressure_torr', 133.322)):
            if getattr(acq, q) is None and ch.get(k) is not None:
                setattr(acq, q, float(f'{ch[k] * f:.4g}'))
        pr = a['profile']
        prof = APTDepthProfile(slice_width=pr['slice'], depth=pr['depth'], ions=pr['ions'], unranged=pr['unranged'])
        if a['element_order']:
            at, err = atomic_percent(pr['per_element'])
            prof.elements = [APTProfileElement(element=el, atomic_percent=np.round(at[:, k], 4),
                                               error=np.round(err[:, k], 4))
                             for k, el in enumerate(a['element_order'])]
        r.depth_profile = prof
        self.results = r
        self.figures = [PlotlyFigure(label=lab, figure=fig) for lab, fig in build_figures(a, ranges)]
        logger.info('APT reconstruction read', ions=a['n_ions'], ranged=a.get('n_ranged'))


class APTRawFile(EntryData):
    """APT file (raw, reconstruction or range file); its data are in the APT measurement entry."""

    m_def = Section(label='APT file')
    file_kind = Quantity(type=MEnum('raw', 'reconstruction', 'range', 'experiment'))
    run = Quantity(type=str)
    apt_entry = Quantity(type=str, description='APT measurement entry (.archive.json) of this run')


m_package.__init_metainfo__()
