#-------------------------------------------------------------------------------
# Name:        ExportFilesToOpenColorado.py
# Purpose:	   This script is a modification of the PublishOpenDataset.py script by Shilo Rohlman 
#              (https://github.com/opencolorado/OpenColorado-Tools-and-Utilities/tree/master/Scripts/ArcGIS/10.0/Python
#              
#              Publish feature class or tables from ArcSDE or FileGeodatabase to
#              the OpenColorado Data Catalog. The publishing process creates
#              output files in a variety of formats that can be shared from local
#              web server. The script uses the CKAN client API to create the dataset
#              reference on OpenColorado if it does not already exist. If the
#              dataset exists on OpenColorado, its revision number will be incremented.
#
#              Modifications include:
#                - Support for tables
#                - Runs entirely in Python
#                - Miscellaneous other refactors that I can't remember now.
#
#              This script completes the following:
#                1) Exports the ArcSDE feature class to the download folder
#                   in the following formats:
#
#                   a. Shapefile (zipped)
#                   b. CAD (dwg file)
#                   c. KML (zipped KMZ)
#                   d. CSV (csv file)
#                   e. Metadata (xml)
#                   f. Esri File Geodatabase (zipped)
#
#              The script automatically manages the creation of output folders if they
#              do not already exist.  Also creates temp folders for processing as
#              needed. The output folder has the following structure. You can start
#              with an empty folder and the script will create the necessary 
#              directories.
#
#              <output_folder>
#              |- <dataset_name> (catalog dataset name with prefix removed, 
#                               dashes replaced with underscores)
#                |- shape
#                    |- <dataset_name>.zip
#                |- cad
#                    |- <dataset_name>.dwg
#                |- kml 
#                    |- <dataset_name>.kmz
#                |- csv 
#                    |- <dataset_name>.csv
#                |- metadata 
#                    |- <dataset_name>.xml
#                |- gdb
#                    |- <dataset_name>.zip
#
#              2) Reads the exported ArcGIS Metadata xml file and parses the relevant
#                 metadata fields to be published to the OpenColorado Data Repository.
#
#              3) Uses the CKAN client API to create a new dataset on the OpenColorado
#                 Data Repository if the dataset does not already exist. If the dataset
#                 already exists, it is updated. 
#
#              4) Updates the version (revision) number of the dataset on the OpenColorado
#                 Data Catalog (if it already exists)
#
# Author:      Tom Neer (tom.neer@digitaldataservices.com)
#              Digital Data Services, Inc.
#
# Licence:     None
#-------------------------------------------------------------------------------

# IMPORTS
import sys, os, logging, logging.config, arcpy, shutil, zipfile, glob, csv, ckanclient, datetime, re
import xml.etree.ElementTree as et

# GLOBALS
staging_feature_class = None
source_feature_class = None
output_folder = None
temp_workspace = None
export_formats = None
ckan_client = None
ckan_group_name = None
ckan_license = None
ckan_download_url = None
metadata_xslt = '..\StyleSheets\Format_FGDC.xslt'
sr_WGS84 = "GEOGCS['GCS_WGS_1984',\
                    DATUM['D_WGS_1984',\
                    SPHEROID['WGS_1984',6378137.0,298.257223563]],\
                    PRIMEM['Greenwich',0.0],\
                    UNIT['Degree',0.0174532925199433]]"

# Transformation method documentation is located in your ArcGIS Desktop install
# at ...\ArcGIS\Desktop10.3\Documentation\geographic_transformations.pdf
transform_WGS84 = 'NAD_1983_To_WGS_1984_5'


# FUNCTIONS
def create_ckan_dataset(dataset_id, ckan_dataset_title, name):
    # Creates a new dataset and registers it to CKAN
    #
    # Params: dataset_id - A string representing the unique dataset name
    # Returns: None

    # Create a new dataset locally
    dataset_entity = create_ckan_local_dataset(dataset_id, ckan_dataset_title)

    # Update the datasets resources (download links)
    dataset_entity = update_ckan_dataset_resources(dataset_entity, ckan_dataset_title, name)

    # Update the dataset from ArcGIS Metadata, if configured
    if 'metadata' in export_formats:
        dataset_entity = update_ckan_local_dataset_from_metadata(dataset_entity, name)

    # Create a new dataset in CKAN
    create_ckan_remote_dataset(dataset_entity)

def create_ckan_local_dataset(dataset_id, ckan_dataset_title):
    # Creates a new dataset entity but does not commit it to CKAN
    #
    # Params: dataset_id - A string representing the unique dataset name
    # Returns: An object structured the same as the JSON dataset output from
    #          the CKAN REST API. For more information on the structure look at the
    #          web service JSON output, or reference:
    #          http://docs.ckan.org/en/latest/api-v2.html#model-api

    global ckan_client

    logger.info('New CKAN Dataset ' + dataset_id + ' being initialized.')
    dataset_entity = {}
    dataset_entity['name'] = dataset_id
    dataset_entity['license_id'] = ckan_license
    dataset_entity['title'] = ckan_dataset_title
	# Version number is a date stamp "20150101"
    dataset_entity['version'] = str(datetime.datetime.now())[:10].replace("-", "")
    dataset_entity['maintainer'] = "Digital Data Services, Inc."
    dataset_entity['maintainer_email'] = "techsupport@digitaldataservices.com"
    dataset_entity['author'] = "Gilpin County Community Development"

    # Find the correct CKAN group id to assign the dataset to
    try:
        group_entity = ckan_client.group_entity_get(ckan_group_name)
        if group_entity is not None:
            logger.info('Adding dataset to group: ' + ckan_group_name)
            dataset_entity['groups'] = [group_entity['id']]
    except ckanclient.CkanApiNotFoundError:
        logger.warn('Problem publishing dataset {0}. Group: {1} not found on CKAN.'.format(dataset_id,ckan_group_name))
        dataset_entity['groups'] = []

    return dataset_entity

def create_ckan_remote_dataset(dataset_entity):
    # Creates a new remote CKAN dataset.
    # The dataset does not yet exists in the CKAN repository, it is created.
    #
    # Parameters: dataset_entity - An object structured the same as the JSON dataset
    #             output from the CKAN REST API. For more information on the structure
    #             look at the web service JSON output, or reference:
    #             http://docs.ckan.org/en/latest/api-v2.html#model-api
    # Returns: None

    global ckan_client
    ckan_client.package_register_post(dataset_entity)

def create_folder(directory, delete=False):
    # Creates a folder if it does not exist
    #
    # Returns: The name of the path
    if os.path.exists(directory) and delete:
        logger.debug('Deleting directory: ' + directory)
        shutil.rmtree(directory)

    if not os.path.exists(directory):
        logger.debug('Directory "' + directory + '" does not exist. Creating...')
        os.makedirs(directory)

    return directory

def create_dataset_folder(name):
    # Creates the output folder for the exported files, if it does not exist
    #
    # Returns: The name of the path
    directory = os.path.join(output_folder, name)
    create_folder(directory)

    return directory

def create_dataset_temp_folder(name):
    # Creates a temporary folder for processing data, if it does not exist
    #
    # Returns: The name of the path
    directory = os.path.join(temp_workspace, name)
    create_folder(directory)

    return directory

def delete_dataset_temp_folder(name):
    # Delete the file geodatabase separately before deleting the
    # the directory to release the locks
    #
    # Returns: None
    gdb_folder = os.path.join(temp_workspace, 'gdb')
    gdb_file = os.path.join(gdb_folder, name + '.gdb')

    if os.path.exists(gdb_file):
        logger.debug('Deleting file geodatabase: ' + gdb_file)
        arcpy.Delete_management(gdb_file)

    dataset_directory = os.path.join(temp_workspace, name)
    if os.path.exists(dataset_directory):
        logger.debug('Deleting directory: ' + dataset_directory)
        shutil.rmtree(dataset_directory)

def drop_exclude_fields(fields):
    # Remove all fields (columns) from the a dataset passed into the exclude-fields parameter
    #
    # Return: None

    # Get the list of fields to exclude
    if fields != None:
        logger.info('Deleting fields: ' + fields)
        fields = fields.replace(',', ';') # Replace commas with semi-colons
        arcpy.DeleteField_management(staging_feature_class, fields)

def export_cad(name):
    # Exports the feature class as a CAD drawing file
    #
    # Returns: None

    # Create cad folder in the temp directory, if it does not exist
    temp_working_folder = os.path.join(temp_workspace, 'cad')
    create_folder(temp_working_folder, True)

    # Export the drawing file
    source = staging_feature_class
    destination = os.path.join(temp_working_folder, name + '.dwg')
    logger.debug('Exporting to DWG file from "' + source + '" to "' + destination + '"')
    arcpy.ExportCAD_conversion(source, 'DWG_R2000', destination, 'Ignore_Filenames_in_Tables', 'Overwrite_Existing_Files', '')

    # Publish the zip file to the out folder
    publish_file(temp_working_folder, name + '.dwg', 'cad')

def export_csv(name):
    # Export the feature class to a CSV file
    #
    # Params: Feature class name
    # Returns: None

    # Create a folder in the temp directory, if it does not exist
    temp_working_folder = os.path.join(temp_workspace, 'csv')
    create_folder(temp_working_folder, True)

    # Export the csv to the temp folder
    source = staging_feature_class
    destination = os.path.join(temp_working_folder, name + '.csv')
    logger.debug('Exporting to csv from "' + source + '" to "' + destination + '"')

    # Get the field names and exclude SHAPE fields
    fieldnames = [f.name for f in arcpy.ListFields(source)]
    if 'Shape' in fieldnames: fieldnames.remove('Shape')
    if 'Shape_Length' in fieldnames: fieldnames.remove('Shape_Length')
    if 'Shape_Area' in fieldnames: fieldnames.remove('Shape_Area')

    # Write the values to csv
    error_report = ''
    error_count = 0
    with open(destination, 'wb') as csvfile:
        writer = csv.writer(csvfile, delimiter=',', quotechar='"', quoting=csv.QUOTE_NONNUMERIC)
        writer.writerow(fieldnames) # Write the header row
        for row in arcpy.da.SearchCursor(source, fieldnames):
            try:
                writer.writerow(row)
            except:
                # Catch any exceptions
                error_count += 1
                error_report = '{0}\n{1}'.format(error_report, row)
                if logger:
                    logger.debug('Error publishing record to CSV for dataset {0}. {1} {2} {3}'.format(name,sys.exc_info()[1], sys.exc_info()[0], row))


    # Log an exception for all records that have failed on this dataset
    if error_count > 0:
        sys.exc_clear()
        logger.exception('Error publishing CSV for dataset {0}. The following records prevented the CSV from publish correctly. Check for invalid characters: {1}'.format(name, error_report))
    else:
        # Publish the csv to the download folder
        publish_file(temp_working_folder, name + '.csv','csv')

def export_file_geodatabase(name, version, datatype):
    # Exports the feature class to a file geodatabase
    #
    # Returns: The name fo the path

    folder = 'gdb'

    # Create a gdb folder in the temp directory, if it does not exist
    temp_working_folder = os.path.join(temp_workspace, folder)
    create_folder(temp_working_folder, True)

    #Export the feature class to a temporary file gdb
    gdb_temp = os.path.join(temp_working_folder, name + '.gdb')
    gdb_feature_class = os.path.join(gdb_temp, name)

    # Create an empty file geodatabase compatible to the supplied version
    if not arcpy.Exists(gdb_temp):
        logger.debug('Creating temp file geodatabase v' + version + ' for processing: ' + gdb_temp)
        arcpy.CreateFileGDB_management(os.path.dirname(gdb_temp), os.path.basename(gdb_temp), version)

    logger.debug('Copying featureclass from: ' + source_feature_class)
    logger.debug('Copying featureclass to: ' + gdb_feature_class)
    if datatype == "FeatureDataset":
        arcpy.CopyFeatures_management(source_feature_class, gdb_feature_class)
    elif datatype == "Table":
        arcpy.TableToGeodatabase_conversion(source_feature_class, gdb_temp)

    return gdb_feature_class

def export_json(name):
    # Exports the feature class to a geoJSON file
    #
    # Returns: None

    # Create a json folder in the temp directory, if it does not exist
    temp_working_folder = os.path.join(temp_workspace, 'json')
    create_folder(temp_working_folder, True)

    # Set the output coordinate system for WGS84
    arcpy.env.outputCoordinateSystem = sr_WGS84
    arcpy.env.geographicTransformations = transform_WGS84

    # Export shapefile to temp folder to remove True Curves
    source = staging_feature_class
    destination = os.path.join(temp_working_folder, name + '.json')
    temp_shapefile = os.path.join(temp_working_folder, name + '.shp')
    logger.debug('Exporting to shapefile from "' + source + '" to "' + destination + '"')
    arcpy.CopyFeatures_management(source, temp_shapefile, '', '0', '0', '0')
    logger.debug('Generating shapefile in memory from "' + temp_shapefile + '"')
    arcpy.MakeFeatureLayer_management(temp_shapefile, name, '', '')

    # Encode special characters that don't convert to KML correctly
    # Replace any literal nulls <NULL> with empty as these don't convert to KML correctly
    replace_literal_nulls(name)

    # Export the JSON to the temp folder
    logger.debug('Exporting the JSON file from "' + temp_shapefile + '" to "' + destination + '"')
    arcpy.FeaturesToJSON_conversion(name, destination, "NOT_FORMATTED", "NO_Z_VALUES", "NO_M_VALUES")

    # Delete the in-memory feature layer
    logger.debug('Deleting in-memory feature layer: ' + name)
    arcpy.Delete_management(name)

    # Publish the file to the out folder
    publish_file(temp_working_folder, name + '.json', 'json')

def export_kml(name):
    # Exports the feature class to a kml file
    #
    # Returns: None

    arcpy.CheckOutExtension('3D')

    # Create a kml folder in the temp directory, if it does not exist
    temp_working_folder = os.path.join(temp_workspace, 'kml')
    create_folder(temp_working_folder, True)
    destination = os.path.join(temp_working_folder, name + '.kmz')

    # Set the output coordinate system for WGS84
    arcpy.env.outputCoordinateSystem = sr_WGS84
    arcpy.env.geographicTransformations = transform_WGS84

    # Make an in-memory feature layer
    logger.debug('Generating KML file in memory from "' + staging_feature_class + '"')
    arcpy.MakeFeatureLayer_management(staging_feature_class, name, '', '')

    # Encode special characters that don't convert to KML correctly
    # Replace any literal nulls <NULL> with empty as these don't convert to KML correctly
    replace_literal_nulls(name)

    # Convert the layer to KML
    logger.debug('Exporting KML file (KMZ) to "' + destination + '"')
    arcpy.LayerToKML_conversion(name, destination, '20000', 'false', 'DEFAULT', '1024', '96')

    # Delete the in-memory feature layer
    logger.debug('Deleting in-memory feature layer: ' + name)
    arcpy.Delete_management(name)

    #Publish the KMZ to the out folder
    publish_file(temp_working_folder, name + '.kmz', 'kml')

def export_metadata(name):
    # Exports the feature class metadata to an xml file
    #
    # Returns: None

    # Create a metadata folder in the temp directory, if it does not exist
    temp_working_folder = os.path.join(temp_workspace, 'metadata')
    create_folder(temp_working_folder, True)

    # Set the destination of the metadata export
    source = staging_feature_class
    raw_metadata_export = os.path.join(temp_working_folder, name + '_raw.xml')

    # Export the metadata
    arcpy.env.workspace = temp_working_folder
    installDir = arcpy.GetInstallInfo('desktop')['InstallDir']
    translator = installDir + 'Metadata/Translator/ARCGIS2FGDC.xml'
    arcpy.ExportMetadata_conversion(source, translator, raw_metadata_export)

    # Process: XSLT Transformation to remove any sensitive info or format
    destination = os.path.join(temp_working_folder, name + '.xml')
    if os.path.exists(metadata_xslt):
        logger.info('Applying metadata XSLT: ' + metadata_xslt)
        arcpy.XSLTransform_conversion(raw_metadata_export, metadata_xslt, destination, '')

        # Reimport the clean metadata into the FGDB
        logger.debug('Reimporting metadata into file geodatabase ' + destination)
        arcpy.MetadataImporter_conversion(destination, staging_feature_class)
    else:
        # If no transformation exists, just rename and publish the raw metadata
        logger.warn('Problem publishing dataset {0}. Metadata XSLT not found.'.format(name))
        os.rename(raw_metadata_export, destination)

    # Publish the metadata to the out folder
    publish_file(temp_working_folder, name + '.xml', 'metadata')


def export_shapefile(name):
    # Exports the feature class to a zipped shapefile
    #
    # Returns: None

    # Create a shape folder in the temp directory, if it does not exist
    temp_working_folder = os.path.join(temp_workspace, 'shp')
    create_folder(temp_working_folder, True)

    # Create a folder for the shapefile (put in a folder to zip)
    zip_folder = os.path.join(temp_working_folder, name)
    create_folder(zip_folder)

    # Export the shapefile to the zip folder
    source = staging_feature_class
    destination = os.path.join(zip_folder, name + '.shp')
    logger.debug('Exporting to shapefile from "' + source + '" to "' + destination + '"')
    arcpy.CopyFeatures_management(source, destination, '', '0', '0', '0')

    # Zip up the files
    logger.debug('Zipping the shapefile')
    zip_file = zipfile.ZipFile(os.path.join(temp_working_folder, name + '.zip'), 'w')

    for filename in glob.glob(zip_folder + '/*'):
        zip_file.write(filename, os.path.basename(filename), zipfile.ZIP_DEFLATED)
    zip_file.close()

    # Publish the zip file to the out folder
    publish_file(temp_working_folder, name + '.zip', 'shp')

def get_resource_by_format(resources, format_type):
    """Searches an array of resources to find the resource that
       matches the file format type passed in. Returns the resource
       if found.

    Parameters:
        resources - An array of CKAN dataset resources
        For more information on the structure look at the
        web service JSON output, or reference:
        http://docs.ckan.org/en/latest/api-v2.html#model-api
        format_type - A string with the file format type to find (SHP, KML..)

    Returns:
        resource - A CKAN dataset resource if found. None if not found.
        For more information on the structure look at the
        web service JSON output, or reference:
        http://docs.ckan.org/en/latest/api-v2.html#model-api
    """

    for resource in resources:
        current_format = resource['format']
        if (str(current_format).strip().upper() == format_type.strip().upper()):
            return resource

    return None

def get_dataset_filename(dataset_name):
    ''' Gets a file system friendly name from the catalog dataset name
    
    Returns: Cleaned dataset name
	'''
	
    return dataset_name.replace('-', '_')

def get_file_size(file_path):
    ''' Gets the size in bytes of the specified file.
    
    Param: file_path - A string with the path to the file
    Result: string - the size in bytes
	'''

    file_size = None

    try:
        file_size = os.path.getsize(file_path)
    except:
        logger.warn('Unable to retrieve file size for resource: {0}.'.format(file_path))
    finally:
        return file_size

def get_remote_dataset(dataset_id):
    # Gets the dataset from CKAN repository
    #
    # Params: dataset_id - A string representing the unique dataset name
    # Returns: An object structured the same as the JSON dataset output from
    #          the CKAN REST API. For more information on the structure look at the
    #          web service JSON output, or reference:
    #          http://docs.ckan.org/en/latest/api-v2.html#model-api

    dataset_entity = None

    try:
        dataset_entity = ckan_client.package_entity_get(dataset_id)
        logger.info('Dataset ' + dataset_id + ' found on OpenColorado')
    except ckanclient.CkanApiNotFoundError:
        logger.info('Dataset ' + dataset_id + ' not found on OpenColorado')

    return dataset_entity

def init_logger(build_target, log_level, dataset_name):
    # Initializes the logger.
    # Adds a filehandler to the logger and outputs a log file
    # for each dataset published

    global logger

    logging.config.fileConfig('Logging.config')

    if build_target == 'PROD':
        logger = logging.getLogger('ProdLogger')
    else:
        logger = logging.getLogger('DefaultLogger')

    # Set the log level passed as a parameter
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % log_level)
    logger.setLevel(numeric_level)

    # Change the name of the logger to the name of this module
    logger.name = 'PublishOpenDataset'

    # Create a file handler and set config the same as the console handler
    # This is done to set the name of the log file name at runtime
    consoleHandler = logger.handlers[0]

    logFileName = 'logs\\' + dataset_name + '.log'
    fileHandler = logging.FileHandler(logFileName, )
    fileHandler.setLevel(consoleHandler.level)
    fileHandler.setFormatter(consoleHandler.formatter)
    logger.addHandler(fileHandler)

def publish_file (directory, file_name, file_type):
    # Publishes as file to the out folder
    #
    # Returns: None

    folder = create_folder(os.path.join(output_folder, file_type))
    logger.info('Copying ' + file_name + ' to ' + folder)
    shutil.copyfile(os.path.join(directory, file_name), os.path.join(folder, file_name))

def publish_file_geodatabase(name):
    # Publishes the already exported file geodatabase to the out folder
    #
    # Returns: None

    # Get the name of the temp gdb directory
    temp_working_folder = os.path.join(temp_workspace, 'gdb')

    # Zip up the gdb folder contents
    logger.debug('Zipping the file geodatabase')
    zip_file_name = os.path.join(temp_working_folder, name + '.zip')
    zip_file = zipfile.ZipFile(zip_file_name, 'w')
    gdb_file_name = os.path.join(temp_working_folder, name + '.gdb')
    for filename in glob.glob(gdb_file_name + '/*'):
        if (not filename.endswith('.lock')):
            zip_file.write(filename, name + '.gdb/' + os.path.basename(filename), zipfile.ZIP_DEFLATED)
    zip_file.close()

    # Publish the file geodatabase to the out folder
    publish_file(temp_working_folder, name + '.zip', 'gdb')

def publish_metadata(name):
    # Publishes the already exported metadata to the out folder
    #
    # Returns: None

    # Create a metadata folder in the temp directory, if it does not exist
    temp_working_folder = os.path.join(temp_workspace, 'metadata')

    # Publish the metadata to the download folder
    publish_file(temp_working_folder, name + '.xml', 'metadata')

def replace_literal_nulls(layer_name):
    # Replace literal <NULL> in attributes with a true null value (None in Python)
    #
    # Return: None

    logger.debug('Start replacing literal NULLs')

    try:
        # Create a list of the fields
        fields = arcpy.ListFields(layer_name)

        # Create an update cursor that will loop through and update each row
        rows = arcpy.UpdateCursor(layer_name)
        for row in rows:
            for field in fields:
                if field.type == 'String':
                    value = row.getValue(field.name)
                    # Ignore null/empty fields
                    if (value != None):
                        # Check for '<Null>' string
                        if (value.find('<Null>') > -1):
                            logger.debug('Found a "<Null>" string to nullify in field: {0}.'.format(field.name))
                            logger.debug('Replacing null string')
                            row.setValue(field.name, '')
                            rows.updateRow(row)

    finally:
        logger.debug('Done replacing literal nulls in {0}.'.format(layer_name))

def slugify_string(in_str):
    """Turns a string into a slug.

    Parameters:
        in_str - The input string.

    Returns:
        A slugified string.
    """

    # Collapse all white space and to a single hyphen
    slug = re.sub('\\s+', '-', in_str)

    # Remove all instances of camel-case text and convert to hyphens. Remove leading and trailing hyphen.
    slug = re.sub('(((?<=[a-z])[A-Z])|([A-Z](?![A-Z]|$)))', '-\\1', slug).lower().strip('-')

    # Collapse any duplicate hyphens
    slug = re.sub('-+', '-', slug)

    return slug;

def update_ckan_dataset(dataset_entity, ckan_dataset_title, name):

    # Update the dataset's resources (download links)
    dataset_entity = update_ckan_dataset_resources(dataset_entity, ckan_dataset_title, name)

    # Update the dataset's version
    dataset_entity['version'] = str(datetime.datetime.now())[:10].replace("-", "")

    # Update the dataset from ArcGIS Metadata (if configured)
    if 'metadata' in export_formats:
        dataset_entity = update_ckan_local_dataset_from_metadata(dataset_entity, name)

    # Update existing dataset in CKAN
    update_ckan_remote_dataset(dataset_entity)

def update_ckan_dataset_resources(dataset_entity, ckan_dataset_title, name):

    global ckan_client

    # Intialize an empty array of resources
    resources = []

    # If the dataset has existing resources, update them
    if ('resources' in dataset_entity):
        resources = dataset_entity['resources']

    # Construct the file resource download urls
    dataset_file_name = get_dataset_filename(name)

    # Get the dataset title (short name)
    title = ckan_dataset_title

    # Export to the various file formats
    if 'shp' in export_formats:
        shp_resource = get_resource_by_format(resources, 'shp')
        if (shp_resource is None):
            logger.info('Creating new SHP resource')
            shp_resource = {}
            resources.append(shp_resource)
        else:
            logger.info('Updating SHP resource')

        shp_resource['name'] = dataset_file_name + " - SHP"
        shp_resource['description'] = dataset_file_name + " - Shapefile"
        shp_resource['url'] = ckan_download_url + dataset_file_name + '/shp/' + dataset_file_name + '.zip'
        shp_resource['mimetype'] = 'application/zip'
        shp_resource['format'] = 'shp'
        shp_resource['resource_type'] = 'file'

        # Get the size of the file
        file_size = get_file_size(output_folder + '\\shp\\' + dataset_file_name + '.zip')
        if file_size:
            shp_resource['size'] = file_size

    if 'dwg' in export_formats:
        dwg_resource = get_resource_by_format(resources, 'dwg')
        if (dwg_resource is None):
            logger.info('Creating new DWG resource.')
            dwg_resource = {}
            resources.append(dwg_resource)
        else:
            logger.info('Updating DWG resource.')

        dwg_resource['name'] = dataset_file_name + " - DWG"
        dwg_resource['description'] = dataset_file_name + " - AutoCAD DWG"
        dwg_resource['url'] = ckan_download_url + dataset_file_name + '/cad/' + dataset_file_name + '.dwg'
        dwg_resource['mimetype'] = 'application/acad'
        dwg_resource['format'] = 'dwg'
        dwg_resource['resource_type'] = 'file'

        # Get the size of the file
        file_size = get_file_size(output_folder + '\\cad\\' + dataset_file_name + '.dwg')
        if file_size:
            dwg_resource['size'] = file_size

    if 'kml' in export_formats:
        kml_resource = get_resource_by_format(resources, 'kml')
        if (kml_resource is None):
            logger.info('Creating new KML resource')
            kml_resource = {}
            resources.append(kml_resource)
        else:
            logger.info('Updating KML resource')

        kml_resource['name'] = title + ' - KML'
        kml_resource['description'] = title  + ' - Google KML'
        kml_resource['url'] = ckan_download_url + dataset_file_name + '/kml/' + dataset_file_name + '.kmz'
        kml_resource['mimetype'] = 'application/vnd.google-earth.kmz'
        kml_resource['format'] = 'kml'
        kml_resource['resource_type'] = 'file'

        # Get the size of the file
        file_size = get_file_size(output_folder + '\\kml\\' + dataset_file_name + '.kmz')
        if file_size:
            kml_resource['size'] = file_size

    if 'json' in export_formats:
        json_resource = get_resource_by_format(resources, 'json')
        if (json_resource is None):
            logger.info('Creating new JSON resource')
            json_resource = {}
            resources.append(json_resource)
        else:
            logger.info('Updating JSON resource')

        json_resource['name'] = dataset_file_name + " - JSON"
        json_resource['description'] = dataset_file_name + " - JSON"
        json_resource['url'] = ckan_download_url + dataset_file_name + '/json/' + dataset_file_name + '.json'
        json_resource['mimetype'] = 'text/json'
        json_resource['format'] = 'json'
        json_resource['resource_type'] = 'file'

        # Get the size of the file
        file_size = get_file_size(output_folder + '\\json\\' + dataset_file_name + '.json')
        if file_size:
            json_resource['size'] = file_size

    if 'csv' in export_formats:
        csv_resource = get_resource_by_format(resources, 'csv')
        if (csv_resource is None):
            logger.info('Creating new CSV resource')
            csv_resource = {}
            resources.append(csv_resource)
        else:
            logger.info('Updating CSV resource')

        csv_resource['name'] = title + ' - CSV'
        csv_resource['description'] = title + ' - Comma-Separated Values'
        csv_resource['url'] = ckan_download_url + dataset_file_name + '/csv/' + dataset_file_name + '.csv'
        csv_resource['mimetype'] = 'text/csv'
        csv_resource['format'] = 'csv'
        csv_resource['resource_type'] = 'file'

        # Get the size of the file
        file_size = get_file_size(output_folder + '\\csv\\' + dataset_file_name + '.csv')
        if file_size:
            csv_resource['size'] = file_size

    if 'metadata' in export_formats:
        metadata_resource = get_resource_by_format(resources, 'XML')
        if (metadata_resource is None):
            logger.info('Creating new Metadata resource')
            metadata_resource = {}
            resources.append(metadata_resource)
        else:
            logger.info('Updating Metadata resource')

        metadata_resource['name'] = title + ' - Metadata'
        metadata_resource['description'] = title + ' - Metadata'
        metadata_resource['url'] = ckan_download_url + dataset_file_name + '/metadata/' + dataset_file_name + '.xml'
        metadata_resource['mimetype'] = 'application/xml'
        metadata_resource['format'] = 'xml'
        metadata_resource['resource_type'] = 'metadata'

        # Get the size of the file
        file_size = get_file_size(output_folder + '\\metadata\\' + dataset_file_name + '.xml')
        if file_size:
            metadata_resource['size'] = file_size

    if 'gdb' in export_formats:
        gdb_resource = get_resource_by_format(resources, 'gdb')
        if (gdb_resource is None):
            logger.info('Creating new gdb resource')
            gdb_resource = {}
            resources.append(gdb_resource)
        else:
            logger.info('Updating GDB resource')

        gdb_resource['name'] = title + ' - GDB'
        gdb_resource['description'] = title + ' - Esri File Geodatabase'
        gdb_resource['url'] = ckan_download_url + dataset_file_name + '/gdb/' + dataset_file_name + '.zip'
        gdb_resource['mimetype'] = 'application/zip'
        gdb_resource['format'] = 'gdb'
        gdb_resource['resource_type'] = 'file'

        # Get the size of the file
        file_size = get_file_size(output_folder + '\\gdb\\' + dataset_file_name + '.zip')
        if file_size:
            gdb_resource['size'] = file_size


    # Update the resources on the dataset
    dataset_entity['resources'] = resources

    return dataset_entity

def update_ckan_local_dataset_from_metadata(dataset_entity, name):
    ''' 
	   Updates the CKAN dataset entity by reading in metadata from the ArcGIS Metadata xml file
	'''

    # Reconstruct the name of the file
    folder = 'metadata'
    working_folder = os.path.join(output_folder, folder)
    file_path = os.path.join(working_folder, name + '.xml')

    # Open the file and read in the xml
    metadata_file = open(file_path, 'r')
    metadata_xml = et.parse(metadata_file)
    metadata_file.close()

    # Get the abstract
    xpath_abstract = '//abstract'
    abstract_element = metadata_xml.find(xpath_abstract)
    if (abstract_element is not None):
        dataset_entity['notes'] = abstract_element.text
    else:
        logger.warn('Problem publishing dataset {0}. No abstract found in metadata.'.format(name))

    # Get the keywords
    keywords = []

    # Get the theme keywords from the ArcGIS Metadata
    xpath_theme_keys = '//themekey'
    theme_keyword_elements = metadata_xml.findall(xpath_theme_keys)

    for keyword_element in theme_keyword_elements:
        keyword = slugify_string(keyword_element.text)
        keywords.append(keyword)
        logger.debug('Keywords found in metadata: ' + keyword)

    dataset_entity['tags'] = keywords

    return dataset_entity

def update_ckan_remote_dataset(dataset_entity):
    global ckan_client

    logger.info('Updating dataset through CKAN API')
    ckan_client.package_entity_put(dataset_entity)

def publish_to_ckan(name):
    # Updates the dataset in the CKAN repository or creates a new dataset
    #
    # Returns: None

    global ckan_client, ckan_license, ckan_group_name, ckan_download_url

    # Parameters
    ckan_api = 'http://data.opencolorado.org/api/2'
    ckan_api_key = '9f087dab-512c-4ca8-a564-8dec444a65db' # This API is not valid, replace
    ckan_dataset_name_prefix = "Gilpin County"
    ckan_group_name = 'gilpin-county'
    ckan_license = 'other-open' # License types can be viewed at http://data.opencolorado.org/api/2/rest/licenses, use the "id" field
    ckan_download_url = "https://data.digitaldataservices.com/GilpinCounty/Data/"

    # Initialize the CKAN Client
    ckan_client = ckanclient.CkanClient(base_location=ckan_api, api_key=ckan_api_key)

    # Create the name of the dataset on the CKAN instance
    dataset_id = ckan_dataset_name_prefix.replace(" ", "-") + "-" + name
    dataset_id = dataset_id.lower() # Make sure everything is lowercase

    # Get the dataset from CKAN
    dataset_entity = get_remote_dataset(dataset_id)

    # Check to see if the dataset exists on CKAN or not
    ckan_dataset_title = ckan_dataset_name_prefix + ": " + name

    if dataset_entity is None:
        # Create a new dataset
        create_ckan_dataset(dataset_id, ckan_dataset_title, name)
    else:
        # Update the existing dataset
        update_ckan_dataset(dataset_entity, ckan_dataset_title, name)

def main(output_location, temp_location, in_file):
    global staging_feature_class, source_feature_class, output_folder, temp_workspace, logger, export_formats

    # Not necessary but done for readability
    source_workspace = in_file[0]
    feature_class = in_file[1]
    dataset_name = in_file[2]
    exclude_fields = in_file[3]
    export_formats = in_file[4]
    gdb_version = in_file[5]
    exe_result = in_file[6]
    build_target = in_file[7]
    log_level = in_file[8]

    # Set the global output folder (trim and append a slash to make sure the files get created inside the directory)
    output_folder = output_location.strip()

    # Set the global temp workspace folder (trim and append a slash to make sure the files get created inside the directory)
    temp_workspace = temp_location.strip()

    # Set the global source feature class
    if source_workspace == None:
        source_feature_class = feature_class
    else:
        source_feature_class = os.path.join(source_workspace, feature_class)

    init_logger(build_target, log_level, dataset_name)

    try:
        logger.info('============================================================')
        logger.info('Starting PublishOpenDataset')
        logger.info('Executing in directory: {0}'.format(os.getcwd()))
        logger.info('Featureclass: {0}'.format(source_feature_class))
        logger.info('Output dataset name: {0}'.format(dataset_name))
        logger.info('Temp folder: {0}'.format(temp_workspace))
        logger.info('Output folder: {0}'.format(output_folder))
        logger.info('Execution type: {0}'.format(exe_result))
        logger.info('Export formats: {0}'.format(export_formats))

        # Delete the dataset temp folder if it exists
        delete_dataset_temp_folder(get_dataset_filename(dataset_name))

        # Create the dataset folder and update the output folder
        output_folder = create_dataset_folder(get_dataset_filename(dataset_name))

        # Create temporary folder for processing and update the temp workspace folder
        temp_workspace = create_dataset_temp_folder(get_dataset_filename(dataset_name))

        # Get dataset type
        desc = arcpy.Describe(source_feature_class)
        in_file_type = desc.datasetType

        # Export and copy formats to the output folder
        if exe_result != 'PUBLISH':

            #Set the output coordinate system for the arcpy environment
            arcpy.env.outputCoordinateSystem = arcpy.SpatialReference(2231)
            arcpy.env.geographicTransformations = None

            # Export to the various file formats
            if (len(export_formats) > 0):
                logger.info('Exporting to file geodatabase')
                staging_feature_class = export_file_geodatabase(get_dataset_filename(dataset_name), gdb_version, in_file_type)
                drop_exclude_fields(exclude_fields)
                export_metadata(get_dataset_filename(dataset_name))

            if 'shp' in export_formats and in_file_type == 'FeatureDataset':
                try:
                    logger.info('Exporting to shapefile')
                    export_shapefile(get_dataset_filename(dataset_name))
                except:
                    if logger:
                        logger.exception('Error publishing shapefile for dataset {0}. {1} {2}'.format(dataset_name,sys.exc_info()[1], sys.exc_info()[0]))

            if 'metadata' in export_formats and in_file_type == 'FeatureDataset':
                try:
                    logger.info('Exporting metadata XML file')
                    publish_metadata(get_dataset_filename(dataset_name))
                except:
                    if logger:
                        logger.exception('Error publishing metadata for dataset {0}. {1} {2}'.format(dataset_name,sys.exc_info()[1], sys.exc_info()[0]))

            if 'gdb' in export_formats and in_file_type == 'FeatureDataset':
                try:
                    logger.info('Publishing file geodatabase')
                    publish_file_geodatabase(get_dataset_filename(dataset_name))
                except:
                    if logger:
                        logger.exception('Error publishing file geodatabase for dataset {0}. {1} {2}'.format(dataset_name,sys.exc_info()[1], sys.exc_info()[0]))

            if 'dwg' in export_formats and in_file_type == 'FeatureDataset':
                try:
                    logger.info('Exporting to CAD drawing file')
                    export_cad(get_dataset_filename(dataset_name))
                except:
                    if logger:
                        logger.exception('Error publishing CAD for dataset {0}. {1} {2}'.format(dataset_name,sys.exc_info()[1], sys.exc_info()[0]))

            if 'json' in export_formats and in_file_type == 'FeatureDataset':
                try:
                    logger.info('Exporting to JSON file')
                    export_json(get_dataset_filename(dataset_name))
                except:
                    if logger:
                        logger.exception('Error publishing JSON for dataset {0}. {1} {2}'.format(dataset_name,sys.exc_info()[1], sys.exc_info()[0]))

            if 'kml' in export_formats and in_file_type == 'FeatureDataset':
                try:
                    logger.info('Exporting to KML file')
                    export_kml(get_dataset_filename(dataset_name))
                except:
                    if logger:
                        logger.exception('Error publishing KML for dataset {0}. {1} {2}'.format(dataset_name,sys.exc_info()[1], sys.exc_info()[0]))

            if 'csv' in export_formats:
                try:
                    logger.info('Exporting to CSV file')
                    export_csv(get_dataset_filename(dataset_name))
                except:
                    if logger:
                        logger.exception('Error publishing CSV for dataset {0}. {1} {2}'.format(dataset_name,sys.exc_info()[1], sys.exc_info()[0]))

        # Update the dataset information on the CKAN repository
        # if the exe_result is equal to 'PUBLISH' or 'BOTH'

        if exe_result != 'EXPORT':
            if len(export_formats) > 0:
                publish_to_ckan(get_dataset_filename(dataset_name))



        logger.info('Done - PublishOpenDataset ' + dataset_name)
        logger.info('============================================================')

    except:
        if logger:
            logger.exception('Error publishing dataset {0}. {1} {2}'.format(dataset_name, sys.exc_info()[1], sys.exc_info()[0]))
        sys.exit(1)

if __name__ == '__main__':
	# The source workspace to publish the feature class from
    # (ex. Database Connections\\\\SDE Connection.sde).
    # Backslashes must be escaped as in the example.
    # source_workspace = r"C:\Users\tmneer.DDS\Desktop\Export\GilpinStaging.gdb"

    # The fully qualified path to the feature class
    # (ex. Database Connections\\\\SDE Connection.sde\\\\schema.parcels).
    # If a source workspace is specified
    # (ex. -s Database Connections\\\\SDE Connection.sde)
    # just the feature class name needs to be provided here (ex. schema.parcels)
    # feature_class = 'BuildingFootprint'

    # The name of the published dataset
    # dataset_name = 'BuildingFootprints'

    # Specifies a comma-delimited list of fields (columns) to remove from the
    # dataset before publishing. (ex. TEMP_FIELD1,TEMP_FIELD2) or None (not "")
    # exclude_fields = None

    # Specific formats to publish (shp=Shapefile, dwg=CAD drawing file,
    # kml=Keyhole Markup Language, metadata=Metadata, gdb=File Geodatabase).
    # If not specified all formats will be published.
    # Choices='shp,dwg,kml,csv,metadata,gdb'
    # export_formats = 'shp,dwg,kml,json,csv,metadata,gdb'

    # The oldest version of Esri ArcGIS file geodatabases need to work with.
    # Choices=['9.2','9.3','10.0','CURRENT']
    # gdb_version = '9.3'

    # Result of executing this script; export data files only, publish to CKAN, or both.
    # Choices=['EXPORT', 'PUBLISH', 'ALL']
    # exe_result = 'EXPORT'

    # The server tier the script is running on.
    # Only PROD supports email alerts
    # Choices=['TEST', 'PROD']
    # build_target = 'TEST'

    # The level of detail to output to log files
    # Choices=['DEBUG','INFO','WARNING','ERROR','CRITICAL','NOTSET']
    # log_level = 'DEBUG'

    output_location = r"F:\Clients\GilpinCounty\Finals\www\Data"
    temp_location = r"F:\Clients\GilpinCounty\_temp\opencolorado"

    files = []

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'AssessorTaxRoll', 'AssessorTaxRoll',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'EXPORT', 'PROD', 'INFO'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'SiteAddressPoint', 'AddressPoints',
                 'notes',
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'PROD', 'INFO'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'BridgePoint', 'BridgePoints',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'PROD', 'INFO'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'BuildingFootprint', 'BuildingFootprints',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'INFO'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'CountyDistrict', 'CommissionerDistricts',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'INFO'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'CountyBoundary', 'CountyBoundaries',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'INFO'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'FiveFootContour', 'Elevation_Contours05Ft',
    #              None,
    #              'shp,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'INFO'])
    #
    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'TenFootContour', 'Elevation_Contours10Ft',
    #              None,
    #              'shp,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'INFO'])
    #
    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'TwentyFootContour', 'Elevation_Contours20Ft',
    #              None,
    #              'shp,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'INFO'])
    #
    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'FortyFootContour', 'Elevation_Contours40Ft',
    #              None,
    #              'shp,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'INFO'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'FacilitySite', 'FacilitySites',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'INFO'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'FacilitySitePoint', 'FacilitySitePoints',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'INFO'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'FEMAFloodZone', 'FEMAFloodZones',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'INFO'])
    #
    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'FireRisk', 'FireRisk',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'INFO'])
    #
    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'Landform', 'Landforms',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])
    #
    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'Mileposts', 'Mileposts',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'MunicipalBoundary', 'MunicipalBoundaries',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'ParcelMaster', 'Parcels',
                 'notes,issdescrip,issflag',
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'PlacePoint', 'PlacePoints',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'PLSSQuarterSection', 'PLSSQuarterSections',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'PLSSSection', 'PLSSSections',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'PLSSTownship', 'PLSSTownships',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'PublicLands', 'PublicLands',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'Railroad', 'Railroad',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'RoadCenterline', 'RoadCenterlines',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'RRCrossing', 'RRCrossings',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])
    #
    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'SchoolBoundary', 'SchoolBoundaries',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'SimultaneousConveyance', 'Subdivisions',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'SnowLoad', 'SnowLoad',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'Trail', 'Trails',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'USNationalGrid', 'USNationalGrid',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'VotingPrecinct', 'VotingPrecincts',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'Waterbody', 'Waterbodies',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'Waterline', 'Waterlines',
                 None,
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'TEST', 'DEBUG'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'Wetlands', 'Wetlands',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'WindLoad', 'WindLoad',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'Zip5', 'ZipCodes',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])

    # files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
    #              'ZoningDistrict', 'ZoningDistricts',
    #              None,
    #              'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
    #              'ALL', 'TEST', 'DEBUG'])

    for file in files:
        main(output_location, temp_location, file)
