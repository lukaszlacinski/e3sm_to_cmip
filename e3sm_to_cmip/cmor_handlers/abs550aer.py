"""
AODABS to abs550aer converter
"""
from __future__ import absolute_import, division, print_function, unicode_literals
import cmor

from e3sm_to_cmip.lib import handle_variables

# list of raw variable names needed
RAW_VARIABLES = [str('AODABS')]
VAR_NAME = str('abs550aer')
VAR_UNITS = str('1')
TABLE = str('CMIP6_AERmon.json')
POSITIVE = str('')

def write_data(varid, data, timeval, timebnds, index):
    """
    abs550aer = AODABS
    """
    outdata = data['AODABS'][index, :]
    cmor.write(
        varid,
        outdata,
        time_vals=timeval,
        time_bnds=timebnds)
# ------------------------------------------------------------------

def handle(infiles, tables, user_input_path, **kwargs):
    """
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
        serial=kwargs.get('serial'),
        positive=POSITIVE)

    return VAR_NAME
# ------------------------------------------------------------------
