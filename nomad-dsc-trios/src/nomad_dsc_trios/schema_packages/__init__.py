from nomad.config.models.plugins import SchemaPackageEntryPoint


class DSCSchemaPackageEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_dsc_trios.schema_packages.dsc import m_package

        return m_package


dsc_sma = DSCSchemaPackageEntryPoint(
    name='DSC_SMA',
    description='DSC on shape memory alloys from TA Instruments TRIOS CSV exports.',
)
