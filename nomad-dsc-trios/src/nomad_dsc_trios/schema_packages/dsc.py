"""DSC on shape memory alloys - schema with built-in TRIOS CSV reading.

Python version of `dsc_sma.archive.yaml`. Differences:
  * `data_file` (top level): attach a TRIOS CSV export; on save/processing the entry
    reads it and fills settings, segments, TRIOS results and the overlay plot.
  * Values entered by hand (specimen description, corrected Ms/Mf/As/Af, ...) are never
    overwritten; only empty fields are filled from the file. Segments and the plot are
    always rebuilt from the file.
"""

import json

import numpy as np
from nomad.datamodel.data import ArchiveSection, EntryData
from nomad.datamodel.metainfo.annotations import ELNAnnotation
from nomad.datamodel.metainfo.plot import PlotlyFigure, PlotSection
from nomad.metainfo import Datetime, Quantity, SchemaPackage, Section, SubSection

from nomad_dsc_trios.trios import overlay_figure, read_trios_csv, read_trios_json

m_package = SchemaPackage(name='DSC on shape memory alloys (TA Instruments TRIOS)')

TIME_ZONE = 'Europe/Prague'  # clock of the DSC PC, used for the run date


def _str(label=None, rich=False, **kw):
    comp = 'RichTextEditQuantity' if rich else 'StringEditQuantity'
    return Quantity(type=str, a_eln=ELNAnnotation(component=comp, label=label), **kw)


def _num(unit, display=None, **kw):
    eln = ELNAnnotation(component='NumberEditQuantity')
    if display:
        eln = ELNAnnotation(component='NumberEditQuantity', defaultDisplayUnit=display)
    return Quantity(type=np.float64, unit=unit, a_eln=eln, **kw)


def _file(description):
    return Quantity(
        type=str,
        description=description,
        a_eln=ELNAnnotation(component='FileEditQuantity'),
        a_browser=dict(adaptor='RawFileAdaptor'),
    )


class DSC_Specimen(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    specimen_id = _str()
    material = _str(description='Alloy designation, e.g. NiTi, NiTiHf, NiTiNb')
    nominal_composition = _str(description='e.g. Ni50.9Ti49.1 (at.%)')
    semi_product = _str(description='Wire, ribbon, sheet, bar, LPBF part ...')
    processing_history = _str(
        rich=True, description='Cold work, heat treatment (temperature, time, quench), training ...'
    )
    mass = _num('kilogram', display='milligram')


class DSC_Settings(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    instrument = _str()
    instrument_serial = _str()
    trios_version = Quantity(type=str)
    exotherm_direction = Quantity(type=str)
    pan_type = _str(description='e.g. Tzero aluminium, hermetic')
    purge_gas = _str()
    purge_flow = _num('milliliter / minute')
    heating_rate = _num('kelvin / minute')
    cooling_rate = _num('kelvin / minute')
    temperature_min = _num('celsius')
    temperature_max = _num('celsius')
    number_of_cycles = Quantity(type=int, a_eln=ELNAnnotation(component='NumberEditQuantity'))
    procedure = _str(rich=True, description='TRIOS procedure (equilibrate, ramp, isothermal ...)')


class DSC_Segment(PlotSection, ArchiveSection):
    m_def = Section(
        label_quantity='name',
        a_plotly_express=dict(
            method='line',
            x='#temperature',
            y='#heat_flow_normalized',
            layout=dict(title=dict(text='Heat flow vs temperature')),
        ),
    )
    name = Quantity(type=str)
    segment_type = Quantity(type=str, description='ramp_cooling, ramp_heating or isothermal')
    rate = Quantity(type=np.float64, unit='kelvin / minute')
    target_temperature = Quantity(type=np.float64, unit='celsius')
    time = Quantity(type=np.float64, unit='second', shape=['*'])
    temperature = Quantity(type=np.float64, unit='celsius', shape=['*'])
    heat_flow_normalized = Quantity(type=np.float64, unit='watt / gram', shape=['*'])


class TRIOS_Analysis(ArchiveSection):
    m_def = Section(label_quantity='model')
    analysed_step = Quantity(type=str)
    model = Quantity(type=str, description='e.g. Onset point, Endset point, Peak integration')
    result_name = Quantity(type=str)
    result_value = Quantity(type=np.float64)
    result_unit = Quantity(type=str)
    details = Quantity(type=str)


class DSC_Measurement(ArchiveSection):
    tri_file = _file('Original TRIOS .tri file in this upload (optional)')
    segments = SubSection(section_def=DSC_Segment, repeats=True)
    trios_analyses = SubSection(section_def=TRIOS_Analysis, repeats=True)


class DSC_Results(ArchiveSection):
    m_def = Section(a_eln=dict(overview=True))
    evaluation_method = _str(description='e.g. tangent method (ASTM F2004), software used')
    Ms = _num('celsius')
    Mf = _num('celsius')
    As = _num('celsius')
    Af = _num('celsius')
    Rs = _num('celsius', description='R-phase start on cooling (if present)')
    Rf = _num('celsius', description='R-phase finish on cooling (if present)')
    peak_temperature_cooling = _num('celsius')
    peak_temperature_heating = _num('celsius')
    enthalpy_cooling = _num('joule / gram')
    enthalpy_heating = _num('joule / gram')
    transformation_sequence = _str(description="e.g. B2-B19', B2-R-B19', multistage")


class DSC_SMA(PlotSection, EntryData):
    """One DSC run on one specimen (TA Instruments TRIOS export)."""

    m_def = Section(label='DSC (SMA, TRIOS)')

    data_file = _file('TRIOS DSC export (.csv or TRIOS JSON .json) in this upload; read on save')
    run_name = _str()
    operator = _str()
    date = Quantity(type=Datetime, a_eln=ELNAnnotation(component='DateTimeEditQuantity'))
    notes = _str(rich=True)

    specimen = SubSection(section_def=DSC_Specimen)
    instrument_settings = SubSection(section_def=DSC_Settings)
    measurement = SubSection(section_def=DSC_Measurement)
    transformation_results = SubSection(section_def=DSC_Results)

    def normalize(self, archive, logger):
        if self.data_file:
            try:
                self._read_data_file(archive, logger)
            except Exception as e:  # keep the entry usable if the file is not readable
                logger.error('could not read the TRIOS DSC file', data_file=self.data_file, exc_info=e)
        if self.run_name and archive.metadata is not None:
            archive.metadata.entry_name = self.run_name  # entry list shows the run, not the file name
        super().normalize(archive, logger)

    def _read_data_file(self, archive, logger):
        n_json_analyses = 0
        with archive.m_context.raw_file(self.data_file, 'r', encoding='utf-8-sig') as f:
            if self.data_file.lower().endswith('.json'):
                data, ramps, n_json_analyses = read_trios_json(json.load(f), self.data_file, tz=TIME_ZONE)
            else:
                data, ramps = read_trios_csv(f.read().splitlines(), self.data_file, tz=TIME_ZONE)
        if n_json_analyses:
            logger.warning('TRIOS analyses in the JSON export are not read yet; enter Ms/Mf/As/Af by hand',
                           analyses=n_json_analyses)

        # top-level quantities: fill only if empty
        for q in ('run_name', 'operator', 'date', 'notes'):
            if q in data and getattr(self, q) is None:
                self.m_update_from_dict({q: data[q]})

        # specimen, settings, results: create if missing, fill only empty quantities
        for name, section_def in (
            ('specimen', DSC_Specimen),
            ('instrument_settings', DSC_Settings),
            ('transformation_results', DSC_Results),
        ):
            values = data.get(name, {})
            if getattr(self, name) is None:
                if not values:
                    continue
                setattr(self, name, section_def())
            target = getattr(self, name)
            missing = {k: v for k, v in values.items() if getattr(target, k) is None}
            if missing:
                target.m_update_from_dict(missing)

        # measurement data and plot: always rebuilt from the file
        tri_file = self.measurement.tri_file if self.measurement else None
        measurement = DSC_Measurement.m_from_dict(data['measurement'])
        if tri_file:  # keep a .tri link the user set by hand
            measurement.tri_file = tri_file
        elif not archive.m_context.raw_path_exists(measurement.tri_file or ''):
            measurement.tri_file = None
        self.measurement = measurement
        # sub-sections are normalized before their parent, so these new segments
        # would otherwise miss their plots
        for segment in measurement.segments:
            segment.normalize(archive, logger)
        self.figures = [PlotlyFigure(label='All ramps', figure=overlay_figure(ramps))]

        logger.info(
            'TRIOS DSC file read',
            data_file=self.data_file,
            segments=len(measurement.segments),
            trios_results=len(measurement.trios_analyses),
        )


class TRIOS_DSC_Export(EntryData):
    """Raw TRIOS DSC export; the measurement itself is in the linked DSC entry."""

    m_def = Section(label='TRIOS DSC export (raw file)')
    dsc_entry = Quantity(type=str, description='DSC entry (.archive.json) created for this file')


m_package.__init_metainfo__()
