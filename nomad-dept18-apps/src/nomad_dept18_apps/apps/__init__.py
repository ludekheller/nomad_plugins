"""Search page 'Dept. 18 lab data': all measurement entries made by the Dept. 18 plugins.

Custom-schema quantities are addressed as  data.<path>#<package.module.Class>  (scalars only).
Quantities stored in units with 'minute' (e.g. heating rate in K/min) are left out: the GUI's
unit library cannot convert them ('Units do not match ... undefined K / minute').
If a schema is renamed or a quantity removed in one of the plugins, update SCHEMAS / the menus here.
"""

from nomad.config.models.plugins import AppEntryPoint
from nomad.config.models.ui import (
    App,
    Axis,
    Column,
    Dashboard,
    Layout,
    Menu,
    MenuItemHistogram,
    MenuItemTerms,
    Pagination,
    SearchQuantities,
    WidgetHistogram,
    WidgetTerms,
)

SCHEMAS = {
    'dsc': 'nomad_dsc_trios.schema_packages.dsc.DSC_SMA',
    'dma': 'nomad_dsc_trios.schema_packages.dma.DMA_TRIOS',
    'instron': 'nomad_thermomech.schema_packages.thermomech.ThermomechTest',
    'walterbai': 'nomad_walterbai.schema_packages.walterbai.WalterBaiTest',
    'tma': 'nomad_linseis.schema_packages.tma.LinseisTMA',
    'apt': 'nomad_apt.schema_packages.apt.APTMeasurement',
    'ir': 'nomad_infratec.schema_packages.ir.IRRecord',
}


def q(schema, path):
    """Search-quantity name of a custom-schema quantity."""
    return f'data.{path}#{SCHEMAS[schema]}'


def terms(schema, path, title, show_input=True):
    return MenuItemTerms(search_quantity=q(schema, path), title=title, show_input=show_input)


def hist(schema, path, title, unit=None):
    # No unit for temperatures stored in degC: the 2.0 GUI converts the histogram step (a
    # temperature *difference*) to the axis unit; for an absolute 'degC' axis that subtracts
    # 273.15, the step becomes negative and the page crashes ('Please provide the value for a
    # Quantity as a number'). Without a unit the axis follows the unit system (K by default).
    if unit == 'degC':
        unit = None
    return MenuItemHistogram(x=Axis(search_quantity=q(schema, path), unit=unit), title=title)


def lay(x, y, w, h):
    one = Layout(x=x, y=y, w=w, h=h, minW=3, minH=3)
    return {bp: one for bp in ('sm', 'md', 'lg', 'xl', 'xxl')}


menu = Menu(
    title='Filters',
    items=[
        Menu(
            title='General',
            items=[
                MenuItemTerms(search_quantity='entry_type', title='Measurement type', show_input=False),
                MenuItemTerms(search_quantity='upload_name', title='Project'),
                MenuItemTerms(search_quantity='authors.name', title='Author'),
                MenuItemHistogram(x=Axis(search_quantity='upload_create_time'), title='Upload time'),
                MenuItemTerms(search_quantity='datasets.dataset_name', title='Dataset'),
            ],
        ),
        Menu(
            title='DSC (TA TRIOS)',
            items=[
                terms('dsc', 'specimen.material', 'Material'),
                terms('dsc', 'specimen.specimen_id', 'Specimen'),
                terms('dsc', 'specimen.semi_product', 'Semi-product'),
                terms('dsc', 'instrument_settings.instrument', 'Instrument'),
                hist('dsc', 'transformation_results.Ms', 'Ms', 'degC'),
                hist('dsc', 'transformation_results.Af', 'Af', 'degC'),
                hist('dsc', 'transformation_results.peak_temperature_cooling', 'Peak T (cooling)', 'degC'),
                hist('dsc', 'transformation_results.peak_temperature_heating', 'Peak T (heating)', 'degC'),
                hist('dsc', 'transformation_results.enthalpy_heating', 'Enthalpy (heating)', 'J/g'),
            ],
        ),
        Menu(
            title='DMA (TA TRIOS)',
            items=[
                terms('dma', 'specimen.material', 'Material'),
                terms('dma', 'specimen.clamp', 'Clamp'),
                terms('dma', 'instrument_settings.instrument', 'Instrument'),
            ],
        ),
        Menu(
            title='Instron / Mercury',
            items=[
                terms('instron', 'specimen.material', 'Material'),
                terms('instron', 'specimen.specimen_id', 'Specimen'),
                terms('instron', 'loading_mode', 'Loading mode', show_input=False),
                terms('instron', 'test_type', 'Test type'),
                terms('instron', 'method', 'Method'),
                terms('instron', 'instrument.testing_machine', 'Testing machine'),
                hist('instron', 'test_temperature', 'Test temperature', 'degC'),
                hist('instron', 'strain_rate', 'Strain rate', '1/s'),
            ],
        ),
        Menu(
            title='Walter+Bai / MITTER',
            items=[
                terms('walterbai', 'testing_machine', 'Testing machine', show_input=False),
                terms('walterbai', 'specimen.material', 'Material'),
                terms('walterbai', 'specimen.specimen_id', 'Specimen'),
                terms('walterbai', 'test_type', 'Test type'),
                hist('walterbai', 'test_temperature', 'Test temperature', 'degC'),
            ],
        ),
        Menu(
            title='Linseis TMA',
            items=[
                terms('tma', 'instrument', 'Instrument', show_input=False),
                terms('tma', 'specimen.material', 'Material'),
                terms('tma', 'specimen.specimen_id', 'Specimen'),
                hist('tma', 'applied_stress', 'Applied stress', 'MPa'),
            ],
        ),
        Menu(
            title='APT (CAMECA LEAP)',
            items=[
                terms('apt', 'instrument', 'Instrument', show_input=False),
                terms('apt', 'specimen.material', 'Material'),
                terms('apt', 'specimen.specimen_id', 'Specimen'),
                terms('apt', 'acquisition.pulse_mode', 'Pulse mode', show_input=False),
                terms('apt', 'acquisition.run_outcome', 'Run outcome', show_input=False),
                hist('apt', 'acquisition.laser_energy', 'Laser energy', 'pJ'),
                hist('apt', 'acquisition.base_temperature', 'Base temperature', 'K'),
                hist('apt', 'results.ions_reconstructed', 'Ions reconstructed'),
            ],
        ),
        Menu(
            title='InfraTec IR camera',
            items=[
                terms('ir', 'purpose', 'Purpose', show_input=False),
                terms('ir', 'camera', 'Camera'),
                terms('ir', 'specimen', 'Specimen'),
                hist('ir', 'peak_temperature', 'Peak temperature', 'degC'),
                hist('ir', 'duration', 'Duration', 's'),
            ],
        ),
    ],
)

columns = [
    Column(search_quantity='entry_name', title='Name', selected=True),
    Column(search_quantity='entry_type', title='Type', selected=True),
    Column(search_quantity='upload_name', title='Project', selected=True),
    Column(search_quantity='authors', selected=True),
    Column(search_quantity='upload_create_time', title='Upload time', selected=True),
    Column(search_quantity='mainfile', title='File'),
    Column(search_quantity='datasets', title='Datasets'),
    Column(search_quantity='published', title='Access'),
    *[Column(search_quantity=q(s, 'specimen.material'), title=f'Material ({s.upper()})')
      for s in ('dsc', 'dma', 'instron', 'walterbai', 'tma', 'apt')],
]

dashboard = Dashboard(
    widgets=[
        WidgetTerms(search_quantity='entry_type', title='Measurement type', scale='linear',
                    show_input=False, layout=lay(0, 0, 8, 8)),
        WidgetHistogram(x=Axis(search_quantity='upload_create_time'), title='Uploads over time',
                        nbins=30, scale='linear', layout=lay(8, 0, 16, 8)),
        WidgetTerms(search_quantity='authors.name', title='Authors', scale='linear',
                    show_input=True, layout=lay(24, 0, 8, 8)),
    ]
)

lab_data_app = AppEntryPoint(
    name='Dept. 18 lab data',
    description='Search page for the measurements of FZU Dept. 18 (DSC, DMA, Instron/Mercury, '
                'Walter+Bai, Linseis TMA, APT, InfraTec IR).',
    app=App(
        label='Dept. 18 lab data',
        path='dept18',
        category='FZU Dept. 18',
        description='Measurements of the Department of Functional Materials',
        readme=(
            'All measurement entries created by the Dept. 18 plugins. Use the filter menus on the '
            'left: **General** for project, author and date; one menu per instrument for its '
            'specific metadata (material, specimen, test temperature, transformation temperatures, ...). '
            'Only entries you are allowed to see are listed: your own, shared with you, or published.'
        ),
        pagination=Pagination(order_by='upload_create_time', order='desc'),
        filters_locked={'section_defs.definition_qualified_name': list(SCHEMAS.values())},
        search_quantities=SearchQuantities(include=[f'*#{s}' for s in SCHEMAS.values()]),
        columns=columns,
        menu=menu,
        dashboard=dashboard,
    ),
)
