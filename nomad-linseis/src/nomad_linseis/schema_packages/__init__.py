from nomad.config.models.plugins import SchemaPackageEntryPoint


class LinseisTMASchemaPackageEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_linseis.schema_packages.tma import m_package

        return m_package


linseis_tma = LinseisTMASchemaPackageEntryPoint(
    name='LinseisTMA',
    description='Linseis TMA PT1000LT / PT1600 runs from text exports.',
)
