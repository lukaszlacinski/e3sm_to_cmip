"""
FISCCP1_COSP to clisccp converter
"""
from __future__ import absolute_import, division, print_function, unicode_literals
from e3sm_to_cmip.util import setup_cmor
from e3sm_to_cmip.util import print_message
from e3sm_to_cmip.lib import my_dynamic_message
import progressbar

import cmor
import cdms2
import logging
import os
logger = logging.getLogger()


# list of raw variable names needed
RAW_VARIABLES = [str('FISCCP1_COSP')]
VAR_NAME = str('clisccp')
VAR_UNITS = str('%')
TABLE = str('CMIP6_CFmon.json')


def write_data(varid, data, timeval, timebnds, index, **kwargs):
    """
    clisccp = FISCCP1_COSP with plev7c, and tau
    """
    cmor.write(
        varid,
        data['FISCCP1_COSP'][index, :],
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

    msg = '{}: Starting'.format(VAR_NAME)
    logger.info(msg)

    nonzero = False
    for variable in RAW_VARIABLES:
        if len(infiles[variable]) == 0:
            msg = '{}: Unable to find input files for {}'.format(
                VAR_NAME, variable)
            print_message(msg)
            logging.error(msg)
            nonzero = True
    if nonzero:
        return None

    msg = '{}: running with input files: {}'.format(
        VAR_NAME,
        infiles)
    logger.debug(msg)

    # setup cmor    
    logdir = kwargs.get('logdir')
    if logdir:
        logfile = logfile = os.path.join(logdir, VAR_NAME + '.log')
    else:
        logfile = os.path.join(os.getcwd(), 'logs')
        if not os.path.exists(logfile):
            os.makedirs(logfile)
        logfile = os.path.join(logfile, VAR_NAME + '.log')

    cmor.setup(
        inpath=tables,
        netcdf_file_action=cmor.CMOR_REPLACE,
        logfile=logfile)
    cmor.dataset_json(user_input_path)
    cmor.load_table(TABLE)

    msg = '{}: CMOR setup complete'.format(VAR_NAME)
    logger.info(msg)

    data = {}

    # assuming all year ranges are the same for every variable
    num_files_per_variable = len(infiles['FISCCP1_COSP'])

    # sort the input files for each variable
    infiles['FISCCP1_COSP'].sort()

    for index in range(num_files_per_variable):

        f = cdms2.open(infiles['FISCCP1_COSP'][index])

        # load the data for each variable
        variable_data = f('FISCCP1_COSP')

        tau = variable_data.getAxis(2)[:]
        tau[-1] = 100.0
        tau_bnds = f.variables['cosp_tau_bnds'][:]
        tau_bnds[-1] = [60.0, 100000.0]

        # load
        data = {
            'FISCCP1_COSP': variable_data,
            'lat': variable_data.getLatitude(),
            'lon': variable_data.getLongitude(),
            'lat_bnds': f('lat_bnds'),
            'lon_bnds': f('lon_bnds'),
            'time': variable_data.getTime(),
            'time_bnds': f('time_bnds'),
            'plev7c': variable_data.getAxis(1)[:] * 100.0,
            'plev7c_bnds': f.variables['cosp_prs_bnds'][:] * 100.0,
            'tau': tau,
            'tau_bnds': tau_bnds
        }

        # create the cmor variable and axis
        axes = [{
            str('table_entry'): str('time'),
            str('units'): data['time'].units
        }, {
            str('table_entry'): str('plev7c'),
            str('units'): str('Pa'),
            str('coord_vals'): data['plev7c'],
            str('cell_bounds'): data['plev7c_bnds']
        }, {
            str('table_entry'): str('tau'),
            str('units'): str('1'),
            str('coord_vals'): data['tau'],
            str('cell_bounds'): data['tau_bnds']
        }, {
            str('table_entry'): str('latitude'),
            str('units'): data['lat'].units,
            str('coord_vals'): data['lat'][:],
            str('cell_bounds'): data['lat_bnds'][:]
        }, {
            str('table_entry'): str('longitude'),
            str('units'): data['lon'].units,
            str('coord_vals'): data['lon'][:],
            str('cell_bounds'): data['lon_bnds'][:]
        }]

        axis_ids = list()
        for axis in axes:
            axis_id = cmor.axis(**axis)
            axis_ids.append(axis_id)

        varid = cmor.variable(VAR_NAME, VAR_UNITS, axis_ids)

       # write out the data
        msg = "{}: time {:1.1f} - {:1.1f}".format(
            VAR_NAME,
            data['time_bnds'][0][0],
            data['time_bnds'][-1][-1])
        logger.info(msg)

        serial = kwargs.get('serial')
        if serial:
            myMessage = progressbar.DynamicMessage('running')
            myMessage.__call__ = my_dynamic_message
            widgets = [
                progressbar.DynamicMessage('running'), ' [',
                progressbar.Timer(), '] ',
                progressbar.Bar(),
                ' (', progressbar.ETA(), ') '
            ]
            progressbar.DynamicMessage.__call__ = my_dynamic_message
            pbar = progressbar.ProgressBar(
                maxval=len(data['time']), widgets=widgets)
            pbar.start()

        for index, val in enumerate(data['time']):
            if serial:
                pbar.update(index, running=msg)
            write_data(
                varid=varid,
                data=data,
                timeval=val,
                timebnds=[data['time_bnds'][index, :]],
                index=index)
            if serial:
                pbar.finish()

    msg = '{}: write complete, closing'.format(VAR_NAME)
    logger.info(msg)

    cmor.close()
    msg = '{}: file close complete'.format(VAR_NAME)
    logger.info(msg)

    return VAR_NAME
# ------------------------------------------------------------------
