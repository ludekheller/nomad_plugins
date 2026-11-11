import importlib

import pytest

from nomad_dept18_apps.apps import SCHEMAS, lab_data_app


def test_app_entry_point():
    app = lab_data_app.app
    assert app.path == 'dept18'
    assert app.filters_locked['section_defs.definition_qualified_name'] == list(SCHEMAS.values())


@pytest.mark.parametrize('path', list(SCHEMAS.values()))
def test_schema_classes_exist(path):
    module, cls = path.rsplit('.', 1)
    section = getattr(importlib.import_module(module), cls)
    assert section.m_def.qualified_name() == path


def test_search_quantities_valid():
    """Same validation as NOMAD's 'validate app' API (needs nomad-lab[infrastructure])."""
    pytest.importorskip('fastapi')
    from nomad.config import config

    config.load_plugins()
    from nomad.datamodel import EntryArchive
    from nomad.metainfo.elasticsearch_extension import entry_type

    entry_type._reset()
    entry_type.create_mapping(EntryArchive.m_def)
    entry_type.reload_quantities_dynamic()
    from nomad.app.v1.routers import apps

    apps.initialize_search_quantities()
    used = apps._build_app_response(lab_data_app.app)['search_quantities']  # raises on unknown names
    assert len(used) > 40


def _histograms(menu):
    for item in menu.items or []:
        if item.type == 'menu':
            yield from _histograms(item)
        elif item.type == 'histogram':
            yield item


def test_no_histogram_on_units_the_gui_cannot_convert():
    """NOMAD 2.0 GUI crashes on histograms of degC or .../minute quantities."""
    for item in _histograms(lab_data_app.app.menu):
        name = item.x.search_quantity
        if '#' not in name:
            continue
        path, schema = name.split('#')
        module, cls = schema.rsplit('.', 1)
        section = getattr(importlib.import_module(module), cls).m_def
        *subs, qname = path.split('.')[1:]
        for sub in subs:
            section = section.all_sub_sections[sub].sub_section
        unit = str(section.all_quantities[qname].unit or '')
        assert 'Celsius' not in unit and 'minute' not in unit, (name, unit)
