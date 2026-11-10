from nomad.config.models.plugins import SchemaPackageEntryPoint


class APTSchemaPackageEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_apt.schema_packages.apt import m_package

        return m_package


apt = APTSchemaPackageEntryPoint(
    name='APTMeasurement',
    description='Atom probe tomography runs: raw files, reconstruction, range file, mass spectrum, composition.',
)
