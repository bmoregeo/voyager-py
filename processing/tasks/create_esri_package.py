# -*- coding: utf-8 -*-
# (C) Copyright 2014 Voyager Search
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import os
import sys
import shutil
import urllib2
from utils import status
from utils import task_utils
from tasks import _


status_writer = status.Writer()
import arcpy


def get_items(input_items, out_workspace):
    """Returns the list of items to package."""
    layers = []
    files = []
    errors = 0
    skipped = 0
    for item in input_items:
        try:
            if item.endswith('.lyr'):
                layers.append(arcpy.mapping.Layer(item))
            else:
                # Is the item a mxd data frame.
                map_frame_name = task_utils.get_data_frame_name(item)
                if map_frame_name:
                    item = item.split('|')[0].strip()
                dsc = arcpy.Describe(item)
                if dsc.dataType in ('FeatureClass', 'ShapeFile', 'RasterDataset'):
                    if dsc.dataType == 'RasterDataset':
                        arcpy.MakeRasterLayer_management(item, os.path.basename(item))
                    else:
                        arcpy.MakeFeatureLayer_management(item, os.path.basename(item))
                    layers.append(arcpy.mapping.Layer(os.path.basename(item)))
                elif dsc.dataType in ('CadDrawingDataset', 'FeatureDataset'):
                    arcpy.env.workspace = item
                    for fc in arcpy.ListFeatureClasses():
                        arcpy.MakeFeatureLayer_management(fc, os.path.basename(fc))
                        layers.append(arcpy.mapping.Layer(os.path.basename(fc)))
                    arcpy.env.workspace = out_workspace
                elif dsc.dataType == 'MapDocument':
                    in_mxd = arcpy.mapping.MapDocument(item)
                    if map_frame_name:
                        df = arcpy.mapping.ListDataFrames(in_mxd, map_frame_name)[0]
                        mxd_layers = arcpy.mapping.ListLayers(in_mxd, data_frame=df)
                    else:
                        mxd_layers = arcpy.mapping.ListLayers(in_mxd)
                    layers += mxd_layers
                elif item.endswith('.gdb') or item.endswith('.mdb'):
                    arcpy.env.workspace = item
                    for fc in arcpy.ListFeatureClasses():
                        arcpy.MakeFeatureLayer_management(fc, os.path.basename(fc))
                        layers.append(arcpy.mapping.Layer(os.path.basename(fc)))
                    for raster in arcpy.ListRasters():
                        arcpy.MakeRasterLayer_management(raster, os.path.basename(raster))
                        layers.append(arcpy.mapping.Layer(os.path.basename(raster)))
                    datasets = arcpy.ListDatasets('*', 'Feature')
                    for fds in datasets:
                        arcpy.env.workspace = fds
                        for fc in arcpy.ListFeatureClasses():
                            arcpy.MakeFeatureLayer_management(fc, os.path.basename(fc))
                            layers.append(arcpy.mapping.Layer(os.path.basename(fc)))
                        arcpy.env.workspace = item
                    arcpy.env.workspace = out_workspace
                elif dsc.dataType == 'File':
                    files.append(item)
                else:
                    status_writer.send_status(_('Invalid input type: {0}').format(item))
                    skipped += 1
                    continue
        except Exception as ex:
            status_writer.send_status(_('Cannot package: {0}: {1}').format(item, repr(ex)))
            errors += 1
            pass
    return layers, files, errors, skipped


def execute(request):
    """Package inputs to an Esri map or layer package.
    :param request: json as a dict.
    """
    errors = 0
    skipped = 0
    layers = []
    files = []

    app_folder = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parameters = request['params']
    out_format = task_utils.get_parameter_value(parameters, 'output_format', 'value')
    summary = task_utils.get_parameter_value(parameters, 'summary')
    tags = task_utils.get_parameter_value(parameters, 'tags')

    # Get the clip region as an extent object.
    clip_area = None
    try:
        clip_area_wkt = task_utils.get_parameter_value(parameters, 'processing_extent', 'wkt')
        clip_area = task_utils.get_clip_region(clip_area_wkt)
    except (KeyError, ValueError):
        pass

    out_workspace = os.path.join(request['folder'], 'temp')
    if not os.path.exists(out_workspace):
        os.makedirs(out_workspace)

    num_results = parameters[0]['response']['numFound']
    if num_results > task_utils.CHUNK_SIZE:
        # Query the index for results in groups of 25.
        query_index = task_utils.QueryIndex(parameters[0])
        fl = query_index.fl
        query = '{0}{1}{2}'.format(sys.argv[2].split('=')[1], '/select?&wt=json', fl)
        fq = query_index.get_fq()
        if fq:
            groups = task_utils.grouper(range(0, num_results), task_utils.CHUNK_SIZE, '')
            query += fq
        else:
            groups = task_utils.grouper(list(parameters[0]['ids']), task_utils.CHUNK_SIZE, '')

        status_writer.send_status(_('Starting to process...'))
        for group in groups:
            if fq:
                results = urllib2.urlopen(query + "&rows={0}&start={1}".format(task_utils.CHUNK_SIZE, group[0]))
            else:
                results = urllib2.urlopen(query + '{0}&ids={1}'.format(fl, ','.join(group)))

            input_items = task_utils.get_input_items(eval(results.read())['response']['docs'])
            layers, files, errors, skipped = get_items(input_items, out_workspace)
    else:
        input_items = task_utils.get_input_items(parameters[0]['response']['docs'])
        layers, files, errors, skipped = get_items(input_items, out_workspace)

    if errors == num_results:
        status_writer.send_state(status.STAT_FAILED, _('No results to package'))
        return

    try:
        if out_format == 'MPK':
            shutil.copyfile(os.path.join(app_folder, 'supportfiles', 'MapTemplate.mxd'),
                            os.path.join(out_workspace, 'output.mxd'))
            mxd = arcpy.mapping.MapDocument(os.path.join(out_workspace, 'output.mxd'))
            if mxd.description == '':
                mxd.description = os.path.basename(mxd.filePath)
            df = arcpy.mapping.ListDataFrames(mxd)[0]
            for layer in layers:
                arcpy.mapping.AddLayer(df, layer)
            mxd.save()
            status_writer.send_status(_('Packaging results...'))
            if arcpy.GetInstallInfo()['Version'] == '10.0':
                arcpy.PackageMap_management(mxd.filePath,
                                            os.path.join(os.path.dirname(out_workspace), 'output.mpk'),
                                            'PRESERVE',
                                            extent=clip_area)
            elif arcpy.GetInstallInfo()['Version'] == '10.1':
                arcpy.PackageMap_management(mxd.filePath,
                                            os.path.join(os.path.dirname(out_workspace), 'output.mpk'),
                                            'PRESERVE',
                                            extent=clip_area,
                                            ArcGISRuntime='RUNTIME',
                                            version='10',
                                            additional_files=files,
                                            summary=summary,
                                            tags=tags)
            else:
                arcpy.PackageMap_management(mxd.filePath,
                                            os.path.join(os.path.dirname(out_workspace), 'output.mpk'),
                                            'PRESERVE',
                                            extent=clip_area,
                                            arcgisruntime='RUNTIME',
                                            version='10',
                                            additional_files=files,
                                            summary=summary,
                                            tags=tags)
            #  Create a thumbnail size PNG of the mxd.
            task_utils.make_thumbnail(mxd, os.path.join(request['folder'], '_thumb.png'))
        else:
            status_writer.send_status(_('Packaging results...'))
            for layer in layers:
                if layer.description == '':
                    layer.description = layer.name
            if arcpy.GetInstallInfo()['Version'] == '10.0':
                arcpy.PackageLayer_management(layers,
                                              os.path.join(os.path.dirname(out_workspace), 'output.lpk'),
                                              'PRESERVE',
                                              extent=clip_area,
                                              version='10')
            else:
                arcpy.PackageLayer_management(layers,
                                              os.path.join(os.path.dirname(out_workspace), 'output.lpk'),
                                              'PRESERVE',
                                              extent=clip_area,
                                              version='10',
                                              additional_files=files,
                                              summary=summary,
                                              tags=tags)
            #  Create a thumbnail size PNG of the mxd.
            task_utils.make_thumbnail(layers[0], os.path.join(request['folder'], '_thumb.png'))
    except (RuntimeError, ValueError, arcpy.ExecuteError) as ex:
        status_writer.send_state(status.STAT_FAILED, repr(ex))
        return

    # Update state if necessary.
    if errors > 0 or skipped:
        status_writer.send_state(status.STAT_WARNING, _('{0} results could not be processed').format(errors + skipped))
    task_utils.report(os.path.join(request['folder'], '_report.json'), len(layers), skipped, errors)
