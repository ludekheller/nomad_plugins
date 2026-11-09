from nomad.config.models.plugins import SchemaPackageEntryPoint


class WalterBaiSchemaPackageEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_walterbai.schema_packages.walterbai import m_package

        return m_package


walterbai = WalterBaiSchemaPackageEntryPoint(
    name='WalterBaiTest',
    description='Thermomechanical tests on the Walter+Bai (UTTRMO) machine with optional 1D DIC.',
)
