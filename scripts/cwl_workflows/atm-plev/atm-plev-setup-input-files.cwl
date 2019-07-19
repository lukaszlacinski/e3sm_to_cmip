#!/usr/bin/env cwl-runner

cwlVersion: v1.0
class: CommandLineTool
baseCommand: [python, /export/baldwin32/projects/e3sm_to_cmip/scripts/cwl_workflows/atm-plev-setup-input-files.py]
stdout: cwl_input_files.yml
requirements:
  - class: InlineJavascriptRequirement

inputs:
  atm_data_path:
    type: string
    inputBinding:
        prefix: --atm_data_path
  start_year:
    type: string
    inputBinding:
        prefix: --start_year
  end_year:
    type: string
    inputBinding:
        prefix: --end_year
  vrtmap_path:
    type: string
  num_workers:
    type: string
    inputBinding:
        prefix: --num_workers
  casename:
    type: string
    inputBinding:
        prefix: --casename
  plev_var_list:
    type: string[]
  year_per_file:
    type: string
    inputBinding:
        prefix: --year_per_file
  hrz_atm_map_path:
    type: string
  native_out_dir:
    type: string
    inputBinding:
        prefix: --native_out_dir
  regrid_out_dir:
    type: string
    inputBinding:
        prefix: --regrid_out_dir

  tables_path: 
    type: string
    inputBinding:
      prefix: --tables_path
  metadata_path: 
    type: string
    inputBinding: 
      prefix: --metadata_path
  cmor_var_list: string[]
  logdir:
    type: string
    inputBinding:
      prefix: --logdir

arguments:
  - prefix: --hrz_atm_mapfile
    valueFrom: $(inputs.hrz_atm_map_path)
  - prefix: --vrtmap
    valueFrom: $(inputs.vrtmap_path)
  - prefix: --plev_var_list
    valueFrom: $(inputs.plev_var_list.join(" "))
  - prefix: --cmor_var_list
    valueFrom: $(inputs.cmor_var_list.join(" "))

outputs:
  cwl_input_files:
    type: stdout