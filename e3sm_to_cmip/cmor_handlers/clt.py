"""
CLDTOT to clt converter
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import cmor
from e3sm_to_cmip.lib import handle_variables

# list of raw variable names needed
RAW_VARIABLES = [str('CLDTOT')]
VAR_NAME = str('clt')
VAR_UNITS = str('%')
TABLE = str('CMIP6_Amon.json')


def write_data(varid, data, timeval, timebnds, index):
    """
    clt = CLDTOT * 100.0
    """
    cmor.write(
        varid,
        data['CLDTOT'][index, :] * 100.0,
        time_vals=timeval,
        time_bnds=timebnds)
# ------------------------------------------------------------------


def handle(infiles, tables, user_input_path, **kwargs):
    """
    Transform E3SM.TS into CMIP.ts

    Parameters
    ----------
        infiles (List): a list of strings of file names for the raw input data
        tables (str): path to CMOR tables
        user_input_path (str): path to user input json file
    Returns
    -------
        var name (str): the name of the processed variable after processing is complete
    """

    handle_variables(
        metadata_path=user_input_path,
        tables=tables,
        table=TABLE,
        infiles=infiles,
        raw_variables=RAW_VARIABLES,
        write_data=write_data,
        outvar_name=VAR_NAME,
        outvar_units=VAR_UNITS,
        serial=kwargs.get('serial'))

    return VAR_NAME
# ------------------------------------------------------------------
