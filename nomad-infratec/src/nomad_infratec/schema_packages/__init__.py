from nomad.config.models.plugins import SchemaPackageEntryPoint


class IRRecordSchemaPackageEntryPoint(SchemaPackageEntryPoint):
    def load(self):
        from nomad_infratec.schema_packages.ir import m_package

        return m_package


ir_record = IRRecordSchemaPackageEntryPoint(
    name='IRRecord',
    description='InfraTec infrared camera record (.tdms): ROI temperatures, profiles and fields vs time.',
)
