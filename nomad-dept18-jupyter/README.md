# nomad-dept18-jupyter

Your NOMAD projects in Jupyter (NORTH) **by name**: raw files by project name, sub-folders and file
name; NOMAD entries and everything NOMAD stored for them (computed values too), for every plugin.

```python
from nomad_dept18_jupyter import nomad

nomad.projects()                    # name, id, folder, published, entries (asks for login once)
f = nomad.path('NAVRATY_ROUDNICKA_3Dtisk_NiTi/3dprinting_params_mapping_001/DSC/niti_slm_hex1121.json.gz')
nomad.find('niti_slm_hex11*')       # files by name (wildcards) in all your projects
nomad.links()                       # ~/work/projects/<project name> -> the project folder

p = nomad.project('NAVRATY_ROUDNICKA_3Dtisk_NiTi')   # or a unique part of the name, or the id
p.folder                            # the project's files (a normal folder, mounted by NOMAD)
p.files('**/*.json.gz')
p.entries()                         # entry_name, entry_type, mainfile, entry_id
e = p.entry('niti_slm_hex11/121')   # entry name, file name or entry id
e.data.transformation_results.Ms    # values as NOMAD stores them (schema units)
e.file()                            # local path of the entry's file
p.table('DSC_SMA', ['specimen.material', 'transformation_results.Ms', 'transformation_results.Af'])
```

* Unpublished projects you can edit are mounted by NOMAD under `~/uploads/<project id>`; files there
  are used directly. **Writing there changes the project.** Files of other projects (published, or
  shared for viewing) are downloaded into `~/work/.nomad_cache`.
* Project names come from the NOMAD API (login with your NOMAD user name and password, once per
  session) and are remembered in `~/work/.nomad_projects.json`, so later sessions find projects by
  name without logging in.
* Installed in the Jupyter image only (`jupyter` extra of my-nomad-oasis); needs `requests`, `pandas`.
