"""Converts data to kml (.kmz)."""
import os
import shutil
import arcpy
from voyager_tasks.utils import status
from voyager_tasks.utils import task_utils


def execute(request):
    """Converts each input dataset to kml (.kmz).
    :param request: json as a dict.
    """
    converted = 0
    skipped = 0

    parameters = request['params']
    in_data = task_utils.find(lambda p: p['name'] == 'input_items', parameters)
    docs = in_data.get('response').get('docs')
    input_items = str(dict((task_utils.get_feature_data(v), v['name']) for v in docs))
    try:
        # Voyager Job Runner: passes a dictionary of inputs and output names.
        input_items = eval(input_items)
    except SyntaxError:
        # If not output names are passed in.
        input_items = dict((k, '') for k in input_items.split(';'))

    count = len(input_items)
    if count > 1:
        out_workspace = os.path.join(request['folder'], 'temp')
    else:
        out_workspace = request['folder']
    if not os.path.exists(out_workspace):
        os.makedirs(out_workspace)

    # Retrieve boundary box extent for input to KML tools.
    extent = ''
    try:
        ext = task_utils.find(lambda p: p['name'] == 'processing_extent', parameters)['wkt']
        if not ext == '':
            extent = task_utils.from_wkt(ext, 4326)
    except KeyError:
        ext = task_utils.find(lambda p: p['name'] == 'processing', parameters)['feature']
        if not ext == '':
            extent = arcpy.Describe(ext).extent

    i = 1.
    status_writer = status.Writer()
    status_writer.send_status('Converting to kml...')
    for ds, out_name in input_items.iteritems():
        try:
            dsc = arcpy.Describe(ds)

            if dsc.dataType == 'FeatureClass':
                arcpy.management.MakeFeatureLayer(ds, dsc.name)
                if out_name == '':
                    out_name = dsc.name
                arcpy.conversion.LayerToKML(dsc.name,
                                            '{0}.kmz'.format(os.path.join(out_workspace, out_name)),
                                            1,
                                            boundary_box_extent=extent)

            elif dsc.dataType == 'ShapeFile':
                arcpy.management.MakeFeatureLayer(ds, dsc.name[:-4])
                if out_name == '':
                    out_name = dsc.name[:-4]
                arcpy.conversion.LayerToKML(dsc.name[:-4],
                                            '{0}.kmz'.format(os.path.join(out_workspace, out_name)),
                                            1,
                                            boundary_box_extent=extent)

            elif dsc.dataType == 'RasterDataset':
                arcpy.management.MakeRasterLayer(ds, dsc.name)
                if out_name == '':
                    out_name = dsc.name
                arcpy.conversion.LayerToKML(dsc.name,
                                            '{0}.kmz'.format(os.path.join(out_workspace, out_name)),
                                            1,
                                            boundary_box_extent=extent)

            elif dsc.dataType == 'Layer':
                if out_name == '':
                    if dsc.name.endswith('.lyr'):
                        out_name = dsc.name[:-4]
                    else:
                        out_name = dsc.name
                arcpy.conversion.LayerToKML(ds,
                                            '{0}.kmz'.format(os.path.join(out_workspace, out_name)),
                                            1,
                                            boundary_box_extent=extent)

            elif dsc.dataType == 'FeatureDataset':
                arcpy.env.workspace = ds
                for fc in arcpy.ListFeatureClasses():
                    arcpy.management.MakeFeatureLayer(fc, 'tmp_lyr')
                    arcpy.conversion.LayerToKML('tmp_lyr',
                                                '{0}.kmz'.format(os.path.join(out_workspace, fc)),
                                                1,
                                                boundary_box_extent=extent)

            elif dsc.dataType == 'CadDrawingDataset':
                arcpy.env.workspace = dsc.catalogPath
                #cad_wks_name = os.path.splitext(dsc.name)[0]
                for cad_fc in arcpy.ListFeatureClasses():
                    if cad_fc.lower() == 'annotation':
                        cad_anno = arcpy.conversion.ImportCADAnnotation(
                            cad_fc,
                            arcpy.CreateUniqueName('cadanno', arcpy.env.scratchGDB)
                        )
                        arcpy.management.MakeFeatureLayer(cad_anno, 'cad_lyr')
                        name = '{0}_{1}'.format(dsc.name[:-4], cad_fc)
                        arcpy.conversion.LayerToKML('cad_lyr',
                                                    '{0}.kmz'.format(os.path.join(out_workspace, name)),
                                                    1,
                                                    boundary_box_extent=extent)
                    else:
                        arcpy.management.MakeFeatureLayer(cad_fc, 'cad_lyr')
                        name = '{0}_{1}'.format(dsc.name[:-4], cad_fc)
                        arcpy.conversion.LayerToKML('cad_lyr',
                                                    '{0}.kmz'.format(os.path.join(out_workspace, name)),
                                                    1,
                                                    boundary_box_extent=extent)

            # Map document to KML.
            elif dsc.dataType == 'MapDocument':
                mxd = arcpy.mapping.MapDocument(ds)
                data_frames = arcpy.mapping.ListDataFrames(mxd)
                for df in data_frames:
                    name = '{0}_{1}'.format(dsc.name[:-4], df.name)
                    arcpy.conversion.MapToKML(ds,
                                              df.name,
                                              '{0}.kmz'.format(os.path.join(out_workspace, name)),
                                              extent_to_export=extent)

            status_writer.send_percent(i/count, 'Converted {0}.'.format(ds), 'convert_to_kml')
            i += 1.
            converted += 1
        except Exception as ex:
            status_writer.send_percent(i/count, 'Failed to convert: {0}. {1}.'.format(ds, ex.message), 'convert_to_kml')
            i += 1
            skipped += 1
            pass

    if count > 1:
        status_writer.send_status('Creating the output zip file: {0}...'.format(os.path.join(out_workspace, 'output.zip')))
        zip_file = task_utils.zip_data(out_workspace, 'output.zip')
        shutil.move(zip_file, os.path.join(os.path.dirname(out_workspace), os.path.basename(zip_file)))

    task_utils.report(os.path.join(request['folder'], '_report.md'), request['task'], converted, skipped)
# End execute function
