'''
Utilities related to converting MPAS-Ocean and MPAS-Seaice files to CMOR
'''

from __future__ import absolute_import, division, print_function

import re
import numpy
import netCDF4
from datetime import datetime
import sys
import xarray
import os
import cmor
import subprocess
import tempfile
import logging
import argparse
from dask.diagnostics import ProgressBar


def remap(ds, mappingFileName, threshold=0.05):
    '''Use ncreamp to remap the xarray Dataset to a new target grid'''

    # write the dataset to a temp file
    inFileName = _get_temp_path()
    outFileName = _get_temp_path()

    if 'depth' in ds.dims:
        ds = ds.transpose('time', 'depth', 'nCells', 'nbnd')

    write_netcdf(ds, inFileName)

    # set an environment variable to make sure we're not using czender's
    # local version of NCO instead of one we have intentionally loaded
    env = os.environ.copy()
    env['NCO_PATH_OVERRIDE'] = 'No'

    args = ['ncremap', '-m', 'mpas', '--d2f', '-7', '--dfl_lvl=1',
            '--no_cll_msr', '--no_frm_trm', '--no_stg_grd', '--msk_src=none',
            '--mask_dst=none', '--map={}'.format(mappingFileName), inFileName,
            outFileName]


    proc = subprocess.Popen(args, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)
    (out, err) = proc.communicate()
    logging.info(out)
    if(proc.returncode):
        print(err)
        raise subprocess.CalledProcessError('ncremap returned {}'.format(
            proc.returncode))

    ds = xarray.open_dataset(outFileName, decode_times=False,
                             mask_and_scale=False)

    if 'depth' in ds.dims:
        ds = ds.transpose('time', 'depth', 'lat', 'lon', 'nbnd')

    ds.load()

    if 'cellMask' in ds:
        mask = ds['cellMask'] > threshold
        norm = 1./ds['cellMask'].where(mask)
        ds = ds.drop('cellMask')
        for varName in ds.data_vars:
            var = ds[varName]
            # make sure all of the mask dimensions are in the variable
            if all([dim in var.dims for dim in mask.dims]):
                ds[varName] = ds[varName].where(mask)*norm

    # remove the temporary files
    os.remove(inFileName)
    os.remove(outFileName)

    return ds


def add_time(ds, dsIn, referenceDate='0001-01-01', offsetYears=0):
    '''Parse the MPAS xtime variable into CF-compliant time'''

    ds = ds.rename({'Time': 'time'})
    dsIn = dsIn.rename({'Time': 'time'})
    xtimeStart = dsIn.xtime_startMonthly
    xtimeEnd = dsIn.xtime_endMonthly
    xtimeStart = [''.join(str(xtimeStart.astype('U'))).strip()
                  for xtimeStart in xtimeStart.values]

    xtimeEnd = [''.join(str(xtimeEnd.astype('U'))).strip()
                for xtimeEnd in xtimeEnd.values]

    # fix xtimeStart, which has an offset by a time step (or so)
    xtimeStart = ['{}_00:00:00'.format(xtime[0:10]) for xtime in xtimeStart]

    daysStart = offsetYears*365 + \
        _string_to_days_since_date(dateStrings=xtimeStart,
                                   referenceDate=referenceDate)

    daysEnd = offsetYears*365 + \
        _string_to_days_since_date(dateStrings=xtimeEnd,
                                   referenceDate=referenceDate)

    time_bnds = numpy.zeros((len(daysStart), 2))
    time_bnds[:, 0] = daysStart
    time_bnds[:, 1] = daysEnd

    days = 0.5*(daysStart + daysEnd)
    ds.coords['time'] = ('time', days)
    ds.time.attrs['units'] = 'days since {}'.format(referenceDate)
    ds.time.attrs['bounds'] = 'time_bnds'

    ds['time_bnds'] = (('time', 'nbnd'), time_bnds)
    ds.time_bnds.attrs['units'] = 'days since {}'.format(referenceDate)
    return ds


def add_depth(ds, dsCoord):
    '''Add a 1D depth coordinate to the data set'''
    if 'nVertLevels' in ds.dims:
        ds = ds.rename({'nVertLevels': 'depth'})

        dsCoord = dsCoord.rename({'nVertLevels': 'depth'})
        depth, depth_bnds = _compute_depth(dsCoord.refBottomDepth)
        ds.coords['depth'] = ('depth', depth)
        ds.depth.attrs['long_name'] = 'reference depth of the center of ' \
                                      'each vertical level'
        ds.depth.attrs['standard_name'] = 'depth'
        ds.depth.attrs['units'] = 'meters'
        ds.depth.attrs['axis'] = 'Z'
        ds.depth.attrs['positive'] = 'down'
        ds.depth.attrs['valid_min'] = depth_bnds[0, 0]
        ds.depth.attrs['valid_max'] = depth_bnds[-1, 1]
        ds.depth.attrs['bounds'] = 'depth_bnds'

        ds.coords['depth_bnds'] = (('depth', 'nbnd'), depth_bnds)
        ds.depth_bnds.attrs['long_name'] = 'Gridcell depth interfaces'

        for varName in ds.data_vars:
            var = ds[varName]
            if 'depth' in var.dims:
                var = var.assign_coords(depth=ds.depth)
                ds[varName] = var

    return ds


def add_mask(ds, mask):
    '''
    Add a 2D or 3D mask to the data sets and multiply all variables by the
    mask
    '''
    ds = ds.copy()
    for varName in ds.data_vars:
        var = ds[varName]
        if all([dim in var.dims for dim in mask.dims]):
            ds[varName] = var.where(mask, 0.)

    ds['cellMask'] = 1.0*mask

    return ds


def add_si_mask(ds, mask, siconc, threshold=0.05):
    '''
    Add a 2D mask to the data sets and apply the mask to all variabels
    '''

    mask = numpy.logical_and(
        mask, siconc > threshold)

    ds = ds.copy()
    for varName in ds.data_vars:
        var = ds[varName]
        if all([dim in var.dims for dim in mask.dims]):
            ds[varName] = var.where(mask, 0.)

    ds['cellMask'] = 1.0*mask

    return ds


def get_cell_masks(dsMesh):
    '''Get 2D and 3D masks of valid MPAS cells from the mesh Dataset'''

    cellMask2D = dsMesh.maxLevelCell > 0

    nVertLevels = dsMesh.sizes['nVertLevels']

    vertIndex = \
        xarray.DataArray.from_dict({'dims': ('nVertLevels',),
                                    'data': numpy.arange(nVertLevels)})

    cellMask3D = vertIndex < dsMesh.maxLevelCell

    return cellMask2D, cellMask3D


def get_sea_floor_values(ds, dsMesh):
    '''Sample fields in the data set at the sea floor'''

    ds = ds.copy()
    cellMask2D = dsMesh.maxLevelCell > 0
    nVertLevels = dsMesh.sizes['nVertLevels']

    # zero-based indexing in python
    maxLevelCell = dsMesh.maxLevelCell - 1

    vertIndex = \
        xarray.DataArray.from_dict({'dims': ('nVertLevels',),
                                    'data': numpy.arange(nVertLevels)})

    for varName in ds.data_vars:
        if 'nVertLevels' not in ds[varName].dims or \
                'nCells' not in ds[varName].dims:
            continue

        # mask only the values with the right vertical index
        ds[varName] = ds[varName].where(maxLevelCell == vertIndex)

        # Each vertical layer has at most one non-NaN value so the "sum"
        # over the vertical is used to collapse the array in the vertical
        # dimension
        ds[varName] = ds[varName].sum(dim='nVertLevels').where(cellMask2D)

    return ds


def open_mfdataset(fileNames, variableList=None,
                   chunks={'nCells': 32768, 'Time': 6}):
    '''Open a multi-file xarray Dataset, retaining only the listed variables'''

    ds = xarray.open_mfdataset(fileNames, concat_dim='Time',
                               mask_and_scale=False, chunks=chunks)

    if variableList is not None:
        allvars = ds.data_vars.keys()

        # get set of variables to drop (all ds variables not in vlist)
        dropvars = set(allvars) - set(variableList)

        # drop spurious variables
        ds = ds.drop(dropvars)

        # must also drop all coordinates that are not associated with the
        # variables
        coords = set()
        for avar in ds.data_vars.keys():
            coords |= set(ds[avar].coords.keys())
        dropcoords = set(ds.coords.keys()) - coords

        # drop spurious coordinates
        ds = ds.drop(dropcoords)

    return ds


def write_netcdf(ds, fileName, fillValues=netCDF4.default_fillvals):
    '''Write an xarray Dataset with NetCDF4 fill values where needed'''
    encodingDict = {}
    variableNames = list(ds.data_vars.keys()) + list(ds.coords.keys())
    for variableName in variableNames:
        isNumeric = numpy.issubdtype(ds[variableName].dtype, numpy.number)
        if isNumeric and numpy.any(numpy.isnan(ds[variableName])):
            dtype = ds[variableName].dtype
            for fillType in fillValues:
                if dtype == numpy.dtype(fillType):
                    encodingDict[variableName] = \
                        {'_FillValue': fillValues[fillType]}
                    break
        else:
            encodingDict[variableName] = {'_FillValue': None}

    update_history(ds)

    ds.to_netcdf(fileName, encoding=encodingDict)


def update_history(ds):
    '''Add or append history to attributes of a data set'''

    thiscommand = datetime.now().strftime("%a %b %d %H:%M:%S %Y") + ": " + \
        " ".join(sys.argv[:])
    if 'history' in ds.attrs:
        newhist = '\n'.join([thiscommand, ds.attrs['history']])
    else:
        newhist = thiscommand
    ds.attrs['history'] = newhist


def convert_namelist_to_dict(fileName):
    '''Convert an MPAS namelist file to a python dictionary'''
    nml = {}

    regex = re.compile(r"^\s*(.*?)\s*=\s*['\"]*(.*?)['\"]*\s*\n")
    with open(fileName) as f:
        for line in f:
            match = regex.findall(line)
            if len(match) > 0:
                nml[match[0][0].lower()] = match[0][1]
    return nml


def setup_cmor(varname, tables, user_input_path, component='ocean'):
    '''Set up CMOR for MPAS-Ocean or MPAS-Seaice'''
    logfile = os.path.join(os.getcwd(), 'logs')
    if not os.path.exists(logfile):
        os.makedirs(logfile)
    logfile = os.path.join(logfile, varname + '.log')
    cmor.setup(
        inpath=tables,
        netcdf_file_action=cmor.CMOR_REPLACE,
        logfile=logfile)
    cmor.dataset_json(str(user_input_path))
    if component == 'ocean':
        table = 'CMIP6_Omon.json'
    elif component == 'seaice':
        table = 'CMIP6_SImon.json'
    else:
        raise ValueError('Unexpected component {}'.format(component))
    try:
        cmor.load_table(table)
    except Exception:
        raise ValueError('Unable to load table from {}'.format(varname))


def write_cmor(axes, ds, varname, varunits, **kwargs):
    '''Write a time series of a variable in the format expected by CMOR'''
    axis_ids = list()
    for axis in axes:
        axis_id = cmor.axis(**axis)
        axis_ids.append(axis_id)

    fillValue = 1e20
    if numpy.any(numpy.isnan(ds[varname])):
        mask = numpy.isfinite(ds[varname])
        ds[varname] = ds[varname].where(mask, fillValue)

    # create the cmor variable
    varid = cmor.variable(str(varname), str(varunits), axis_ids,
                          missing_value=fillValue, **kwargs)

    # write out the data
    try:
        cmor.write(
            varid,
            ds[varname].values,
            time_vals=ds.time.values,
            time_bnds=ds.time_bnds.values)
    except Exception as error:
        logging.exception('Error in cmor.write for {}'.format(varname))
        raise
    finally:
        cmor.close(varid)


def compute_moc_streamfunction(dsIn=None, dsMesh=None, dsMasks=None,
                               showProgress=True):
    '''
    An entry point to compute the MOC streamfunction (including Bolus velocity)
    and write it to a new file.
    '''

    useCommandLine = dsIn is None and dsMesh is None and dsMasks is None

    if useCommandLine:
        # must be running from the command line

        parser = argparse.ArgumentParser(
            description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
        parser.add_argument("-m", "--meshFileName", dest="meshFileName",
                            type=str, required=True,
                            help="An MPAS file with mesh data (edgesOnCell, "
                                 "etc.)")
        parser.add_argument("-r", "--regionMasksFileName",
                            dest="regionMasksFileName", type=str,
                            required=True,
                            help="An MPAS file with MOC region masks")
        parser.add_argument("-i", "--inFileNames", dest="inFileNames",
                            type=str, required=True,
                            help="An MPAS monthly mean files from which to "
                                 "compute transport.")
        parser.add_argument("-o", "--outFileName", dest="outFileName",
                            type=str, required=True,
                            help="An output MPAS file with transport time "
                                 "series")
        args = parser.parse_args()

        dsMesh = xarray.open_dataset(args.meshFileName)
        dsMesh = dsMesh.isel(Time=0, drop=True)

        dsMasks = xarray.open_dataset(args.regionMasksFileName)

        variableList = ['timeMonthly_avg_normalVelocity',
                        'timeMonthly_avg_normalGMBolusVelocity',
                        'timeMonthly_avg_vertVelocityTop',
                        'timeMonthly_avg_vertGMBolusVelocityTop',
                        'timeMonthly_avg_layerThickness',
                        'xtime_startMonthly', 'xtime_endMonthly']

        dsIn = open_mfdataset(args.inFileNames, variableList)

    dsOut = xarray.Dataset()

    dsIn = dsIn.chunk(chunks={'nCells': None, 'nVertLevels': None,
                              'Time': 6})

    cellsOnEdge = dsMesh.cellsOnEdge - 1

    totalNormalVelocity = \
        (dsIn.timeMonthly_avg_normalVelocity +
         dsIn.timeMonthly_avg_normalGMBolusVelocity)
    layerThickness = dsIn.timeMonthly_avg_layerThickness

    layerThicknessEdge = 0.5*(layerThickness[:, cellsOnEdge[:, 0], :] +
                              layerThickness[:, cellsOnEdge[:, 1], :])

    totalVertVelocityTop = \
        (dsIn.timeMonthly_avg_vertVelocityTop +
         dsIn.timeMonthly_avg_vertGMBolusVelocityTop)

    moc, coords = _compute_moc_time_series(totalNormalVelocity,
                                           totalVertVelocityTop,
                                           layerThicknessEdge, dsMesh,
                                           dsMasks, showProgress)
    dsOut['moc'] = moc
    dsOut = dsOut.assign_coords(**coords)

    dsOut = add_time(dsOut, dsIn)

    if useCommandLine:
        dsOut = dsOut.chunk({'lat': None, 'depth': None, 'time': 1,
                             'basin': 1})

        for attrName in dsIn.attrs:
            dsOut.attrs[attrName] = dsIn.attrs[attrName]

        time = datetime.now().strftime('%c')

        history = '{}: {}'.format(time, ' '.join(sys.argv))

        if 'history' in dsOut.attrs:
            dsOut.attrs['history'] = '{}\n{}'.format(history,
                                                     dsOut.attrs['history'])
        else:
            dsOut.attrs['history'] = history

        write_netcdf(dsOut, args.outFileName)
    else:
        return dsOut


def interp_vertex_to_cell(varOnVertices, dsMesh):
    """ Interpolate a 2D field on vertices to MPAS cell centers """
    nCells = dsMesh.sizes['nCells']
    vertexDegree = dsMesh.sizes['vertexDegree']
    maxEdges = dsMesh.sizes['maxEdges']

    kiteAreas = dsMesh.kiteAreasOnVertex.values
    verticesOnCell = dsMesh.verticesOnCell.values-1
    cellsOnVertex = dsMesh.cellsOnVertex.values-1

    cellIndices = numpy.arange(nCells)

    weights = numpy.zeros((nCells, maxEdges))
    for iVertex in range(maxEdges):
        vertices = verticesOnCell[:, iVertex]
        mask1 = vertices > 0
        for iCell in range(vertexDegree):
            mask2 = numpy.equal(cellsOnVertex[vertices, iCell], cellIndices)
            mask = numpy.logical_and(mask1, mask2)
            weights[:, iVertex] += mask * kiteAreas[vertices, iCell]

    weights =  \
        xarray.DataArray.from_dict({'dims': ('nCells', 'maxEdges'),
                                    'data': weights})

    weights /= dsMesh.areaCell

    varOnVertices = varOnVertices.chunk(chunks={'nVertices': None, 'Time': 36})

    varOnCells = (varOnVertices[:, dsMesh.verticesOnCell-1]*weights).sum(
        dim='maxEdges')

    varOnCells.compute()

    return varOnCells


def _string_to_days_since_date(dateStrings, referenceDate='0001-01-01'):
    """
    Turn an array-like of date strings into the number of days since the
    reference date

    """

    dates = [_string_to_datetime(string) for string in dateStrings]
    days = _datetime_to_days(dates, referenceDate=referenceDate)

    days = numpy.array(days)
    return days


def _string_to_datetime(dateString):
    """ Given a date string and a calendar, returns a datetime.datetime"""

    (year, month, day, hour, minute, second) = \
        _parse_date_string(dateString)

    return datetime(year=year, month=month, day=day, hour=hour,
                    minute=minute, second=second)


def _parse_date_string(dateString):
    """
    Given a string containing a date, returns a tuple defining a date of the
    form (year, month, day, hour, minute, second) appropriate for constructing
    a datetime or timedelta
    """

    # change underscores to spaces so both can be supported
    dateString = dateString.replace('_', ' ').strip()
    if ' ' in dateString:
        ymd, hms = dateString.split(' ')
    else:
        if '-' in dateString:
            ymd = dateString
            # error can result if dateString = '1990-01'
            # assume this means '1990-01-01'
            if len(ymd.split('-')) == 2:
                ymd += '-01'
            hms = '00:00:00'
        else:
            ymd = '0001-01-01'
            hms = dateString

    if '.' in hms:
        hms = hms.replace('.', ':')

    if '-' in ymd:
        (year, month, day) \
            = [int(sub) for sub in ymd.split('-')]
    else:
        day = int(ymd)
        year = 0
        month = 1

    if ':' in hms:
        (hour, minute, second) \
            = [int(sub) for sub in hms.split(':')]
    else:
        second = int(hms)
        minute = 0
        hour = 0
    return (year, month, day, hour, minute, second)


def _datetime_to_days(dates, referenceDate='0001-01-01'):
    """
    Given dates and a reference date, returns the days since
    the reference date as an array of floats.
    """

    days = netCDF4.date2num(dates, 'days since {}'.format(referenceDate),
                            calendar='noleap')

    return days


def _compute_depth(refBottomDepth):
    """
    Computes depth and depth bounds given refBottomDepth

    Parameters
    ----------
    refBottomDepth : ``xarray.DataArray``
        the depth of the bottom of each vertical layer in the initial state
        (perfect z-level coordinate)

    Returns
    -------
    depth : ``xarray.DataArray``
        the vertical coordinate defining the middle of each layer
    depth_bnds : ``xarray.DataArray``
        the vertical coordinate defining the top and bottom of each layer
    """
    # Authors
    # -------
    # Xylar Asay-Davis

    refBottomDepth = refBottomDepth.values

    depth_bnds = numpy.zeros((len(refBottomDepth), 2))

    depth_bnds[0, 0] = 0.
    depth_bnds[1:, 0] = refBottomDepth[0:-1]
    depth_bnds[:, 1] = refBottomDepth
    depth = 0.5*(depth_bnds[:, 0] + depth_bnds[:, 1])

    return depth, depth_bnds


def _compute_moc_time_series(normalVelocity, vertVelocityTop,
                             layerThicknessEdge, dsMesh, dsMasks,
                             showProgress):
    '''compute MOC time series as a post-process'''

    dvEdge = dsMesh.dvEdge
    areaCell = dsMesh.areaCell
    latCell = numpy.rad2deg(dsMesh.latCell)
    nTime = normalVelocity.sizes['Time']
    nCells = dsMesh.sizes['nCells']
    nVertLevels = dsMesh.sizes['nVertLevels']

    nRegions = 1 + dsMasks.sizes['nRegions']

    regionNames = ['Global'] + [str(name.values) for name in
                                dsMasks.regionNames]

    latBinSize = 1.0

    lat = numpy.arange(-90., 90. + latBinSize, latBinSize)
    lat_bnds = numpy.zeros((len(lat)-1, 2))
    lat_bnds[:, 0] = lat[0:-1]
    lat_bnds[:, 1] = lat[1:]
    lat = 0.5*(lat_bnds[:, 0] + lat_bnds[:, 1])

    lat_bnds = xarray.DataArray(lat_bnds, dims=('lat', 'nbnd'))
    lat = xarray.DataArray(lat, dims=('lat',))

    depth, depth_bnds = _compute_depth(dsMesh.refBottomDepth)

    depth_bnds = xarray.DataArray(depth_bnds, dims=('depth', 'nbnd'))
    depth = xarray.DataArray(depth, dims=('depth',))

    transport = {}
    transport['Global'] = xarray.DataArray(numpy.zeros((nTime, nVertLevels)),
                                           dims=('Time', 'nVertLevels',))

    cellMasks = {}
    cellMasks['Global'] = xarray.DataArray(numpy.ones(nCells),
                                           dims=('nCells',))

    for regionIndex in range(1, nRegions):
        regionName = regionNames[regionIndex]
        dsMask = dsMasks.isel(nTransects=regionIndex-1, nRegions=regionIndex-1)
        edgeIndices = dsMask.transectEdgeGlobalIDs
        mask = edgeIndices > 0
        edgeIndices = edgeIndices[mask] - 1
        edgeSigns = dsMask.transectEdgeMaskSigns[edgeIndices]
        v = normalVelocity[:, edgeIndices, :]
        h = layerThicknessEdge[:, edgeIndices, :]
        dv = dvEdge[edgeIndices]
        transport[regionName] = (v*h*dv*edgeSigns).sum(
            dim='maxEdgesInTransect')

        _compute_dask(transport[regionName], showProgress,
                      'Computing transport through southern boundary of '
                      '{}'.format(regionName))

        cellMasks[regionName] = dsMask.regionCellMasks
        cellMasks[regionName].compute()

    mocs = {}

    for regionName in regionNames:
        mocSlice = numpy.zeros((nTime, nVertLevels+1))
        mocSlice[:, 1:] = transport[regionName].cumsum(
            dim='nVertLevels').values

        mocSlice = xarray.DataArray(mocSlice,
                                    dims=('Time', 'nVertLevelsP1'))
        mocSlices = [mocSlice]
        binCounts = []
        for iLat in range(lat_bnds.sizes['lat']):
            mask = numpy.logical_and(numpy.logical_and(
                cellMasks[regionName] == 1, latCell >= lat_bnds[iLat, 0]),
                latCell < lat_bnds[iLat, 1])
            binCounts.append(numpy.count_nonzero(mask))
            mocTop = mocSlices[iLat] + (vertVelocityTop[:, mask, :] *
                                        areaCell[mask]).sum(dim='nCells')
            mocSlices.append(mocTop)

        moc = xarray.concat(mocSlices, dim='lat')
        moc = moc.transpose('Time', 'nVertLevelsP1', 'lat')
        # average to bin and level centers
        moc = 0.25*(moc[:, 0:-1, 0:-1] + moc[:, 0:-1, 1:] +
                    moc[:, 1:, 0:-1] + moc[:, 1:, 1:])
        moc = moc.rename({'nVertLevelsP1': 'depth'})
        binCounts = xarray.DataArray(binCounts, dims=('lat'))
        moc = moc.where(binCounts > 0)

        _compute_dask(moc, showProgress, 'Computing {} MOC'.format(regionName))

        mocs[regionName] = moc

    mocs = xarray.concat(mocs.values(), dim='basin')
    mocs = mocs.transpose('Time', 'basin', 'depth', 'lat')

    regionNames = xarray.DataArray(regionNames, dims=('basin',))

    coords = dict(lat=lat, lat_bnds=lat_bnds, depth=depth,
                  depth_bnds=depth_bnds, regionNames=regionNames)

    return mocs, coords


def _compute_dask(ds, showProgress, message):

    if showProgress:
        print(message)
        with ProgressBar():
            ds.compute()
    else:
        ds.compute()


def _get_temp_path():
    '''Returns the name of a temporary NetCDF file'''
    return '{}/{}.nc'.format(tempfile.gettempdir(),
                             next(tempfile._get_candidate_names()))