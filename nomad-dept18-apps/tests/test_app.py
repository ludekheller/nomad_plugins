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
