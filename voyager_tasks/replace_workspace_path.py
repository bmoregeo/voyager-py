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
import shutil
import arcpy
from voyager_tasks.utils import status
from voyager_tasks.utils import task_utils


def execute(request):
    """Replace the workspace path for layer files and map document layers.
    :param request: json as a dict.
    """
    updated = 0
    skipped = 0
    status_writer = status.Writer()
    parameters = request['params']
    input_items = task_utils.get_input_items(parameters)
    backup = task_utils.get_parameter_value(parameters, 'create_backup', 'value')
    old_workspace = task_utils.get_parameter_value(parameters, 'old_workspace_path', 'value').lower()
    new_workspace = task_utils.get_parameter_value(parameters, 'new_workspace_path', 'value')

    if not os.path.exists(request['folder']):
        os.makedirs(request['folder'])

    workspace_types = {'.mdb': 'ACCESS_WORKSPACE', '.gdb': 'FILEGDB_WORKSPACE', '.sde': 'SDE_WORKSPACE', '': 'NONE'}
    workspace_type = workspace_types[os.path.splitext(new_workspace)[1]]
    for item in input_items:
        layers = None
        table_views = None
        mxd = None
        if item.endswith('.lyr') or item.endswith('.mxd'):
            if backup:
                try:
                    shutil.copyfile(item, '{0}.bak'.format(item))
                except IOError as ex:
                    status_writer.send_status(_('Cannot make a backup of: {0}').format(item))
                    skipped += 1
                    continue
            if item.endswith('.lyr'):
                layer_from_file = arcpy.mapping.Layer(item)
                layers = arcpy.mapping.ListLayers(layer_from_file)
            else:
                mxd = arcpy.mapping.MapDocument(item)
                layers = arcpy.mapping.ListLayers(mxd)
                table_views = arcpy.mapping.ListTableViews(mxd)
        else:
            status_writer.send_status(_('{0} is not a layer file or map document').format(item))
            skipped += 1
            continue

        if layers:
            for layer in layers:
                try:
                    if layer.isFeatureLayer:
                        if layer.workspacePath.lower().find(old_workspace) > -1:
                            new_source = layer.workspacePath.lower().replace(old_workspace, new_workspace)
                            layer.replaceDataSource(new_source, workspace_type, validate=True)
                    elif layer.isRasterLayer:
                        if layer.workspacePath.lower().find(old_workspace) > -1:
                            new_source = layer.workspacePath.lower().replace(old_workspace, new_workspace)
                            if not workspace_type == 'NONE':
                                layer.replaceDataSource(new_source, workspace_type, validate=True)
                            else:
                                layer.replaceDataSource(new_source, 'RASTER_WORKSPACE', validate=True)
                    if item.endswith('.lyr'):
                        layer.save()
                except ValueError:
                    status_writer.send_status(_('Invalid workspace'))
                    skipped += 1
                    pass

        if table_views:
            for table_view in table_views:
                try:
                    if table_view.workspacePath.lower().find(old_workspace) > -1:
                        new_source = table_view.workspacePath.lower().replace(old_workspace, new_workspace)
                        table_view.replaceDataSource(new_source, workspace_type, validate=False)
                except ValueError:
                    status_writer.send_status(_('Invalid workspace'))
                    skipped += 1
                    pass
        if mxd:
            mxd.save()

        updated += 1

    try:
        shutil.copy2(os.path.join(os.path.dirname(__file__), 'supportfiles', '_thumb.png'), request['folder'])
    except IOError:
        pass

    # Update state if necessary.
    if skipped > 0:
        status_writer.send_state(status.STAT_WARNING, _('{0} results could not be processed').format(skipped))
    task_utils.report(os.path.join(request['folder'], '_report.json'), updated, skipped)