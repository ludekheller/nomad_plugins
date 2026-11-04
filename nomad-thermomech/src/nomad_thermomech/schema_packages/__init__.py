from nomad.config.models.plugins import SchemaPackageEntryPoint


class ThermomechSchemaPackageEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_thermomech.schema_packages.thermomech import m_package

        return m_package


thermomech = ThermomechSchemaPackageEntryPoint(
    name='ThermomechTest',
    description='Thermomechanical tests on SMAs: Instron WaveMatrix + Mercury RT DIC.',
)
