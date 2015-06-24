## ExportToOpenColorado

Publish feature class or tables from ArcSDE or FileGeodatabase to the OpenColorado Data Catalog. The publishing process creates output files in a variety of formats that can be shared from local web server. The script uses the CKAN client API to create the dataset reference on OpenColorado if it does not already exist. If the dataset exists on OpenColorado, its revision number will be incremented. This script is a modification of the PublishOpenDataset.py script by Shilo Rohlman (https://github.com/opencolorado/OpenColorado-Tools-and-Utilities/tree/master/Scripts/ArcGIS/10.0/Python)

**Modifications include:**
  - Support for tables
  - Runs entirely in Python
  - Miscellaneous other refactors that I can't remember now.

**This script completes the following:**
  1. Exports the ArcSDE feature class to the download folder in the following formats:
    a. Shapefile (zipped)
    b. CAD (dwg file)
    c. KML (zipped KMZ)
    d. CSV (csv file)
    e. Metadata (xml)
    f. Esri File Geodatabase (zipped)

The script automatically manages the creation of output folders if they do not already exist.  Also creates temp folders for processing as needed. The output folder has the following structure. You can start with an empty folder and the script will create the necessary directories.

<output_folder>
|- <dataset_name> (catalog dataset name with prefix removed, dashes replaced with underscores)
  |- shape
    |- <dataset_name>.zip
  |- cad
    |- <dataset_name>.dwg
  |- kml 
    |- <dataset_name>.kmz
  |- csv 
    |- <dataset_name>.csv
  |- metadata 
    |- <dataset_name>.xml
  |- gdb
    |- <dataset_name>.zip

  2. Reads the exported ArcGIS Metadata xml file and parses the relevant metadata fields to be published to the OpenColorado Data Repository.

  3. Uses the CKAN client API to create a new dataset on the OpenColorado Data Repository if the dataset does not already exist. If the dataset already exists, it is updated. 

  4. Updates the version (revision) number of the dataset on the OpenColorado Data Catalog (if it already exists)

Author: Tom Neer (tom.neer@digitaldataservices.com), Digital Data Services, Inc.
Licence: None

**Instructions**

  1. Install ckanclient (https://pypi.python.org/pypi/ckanclient) library into your Python install
  2. Configure your projection transformation method - On line 32, set the transform_WGS84 to the appropriate transformation method for your data. All data is exported in their native projection, however, KML and JSON are projected into WGS84. You will need to set the appropriate Transformation method. Gilpin County uses Colorado State Plane North NAD83 so the appropriate transformation method is 'NAD_1983_To_WGS_1984_5'
  3. Configure OpenColorado variables
    - Line 130, set the dataset_entity['maintainer']
	- Line 131, set the dataset_entity['maintainer_email']
	- Line 132, set the dataset_entity['author']
	- Line 884, set your ckan_api_key, obtained from your OpenColorado Profile
	- Line 885, set your dataset name
	- Line 886, set your group name
	- Line 887, set your ckan_license. License types can be viewed at http://data.opencolorado.org/api/2/rest/licenses, use the "id" field
	- Line 888, the base url for where your datasets will be stored with access from Internet
	
  4. Configure Datasets to export
	- Line 1093, set the output directory path of where the processed files will be stored. This is the directory path to the base URL
	- Line 1094, set the temp directory path of where the temp files will be stored.
	
  5. Append datasets that you want to export using the provided examples starting at Line 1098.
  The source workspace to publish the feature class from
    (ex. Database Connections\\\\SDE Connection.sde).
    Backslashes must be escaped as in the example.
    source_workspace = r"C:\Users\tmneer.DDS\Desktop\Export\GilpinStaging.gdb"

    The fully qualified path to the feature class
    (ex. Database Connections\\\\SDE Connection.sde\\\\schema.parcels).
    If a source workspace is specified
    (ex. -s Database Connections\\\\SDE Connection.sde)
    just the feature class name needs to be provided here (ex. schema.parcels)
    feature_class = 'BuildingFootprint'

    The name of the published dataset
    dataset_name = 'BuildingFootprints'

    Specifies a comma-delimited list of fields (columns) to remove from the
    dataset before publishing. (ex. TEMP_FIELD1,TEMP_FIELD2) or None (not "")
    exclude_fields = None

    Specific formats to publish (shp=Shapefile, dwg=CAD drawing file,
    kml=Keyhole Markup Language, metadata=Metadata, gdb=File Geodatabase).
    If not specified all formats will be published.
    Choices='shp,dwg,kml,csv,metadata,gdb'
    export_formats = 'shp,dwg,kml,json,csv,metadata,gdb'

    The oldest version of Esri ArcGIS file geodatabases need to work with.
    Choices=['9.2','9.3','10.0','CURRENT']
    gdb_version = '9.3'

    Result of executing this script; export data files only, publish to CKAN, or both.
    Choices=['EXPORT', 'PUBLISH', 'ALL']
    exe_result = 'EXPORT'

    The server tier the script is running on.
    Only PROD supports email alerts
    Choices=['TEST', 'PROD']
    build_target = 'TEST'

    The level of detail to output to log files
    Choices=['DEBUG','INFO','WARNING','ERROR','CRITICAL','NOTSET']
    log_level = 'DEBUG'

Structure:
    files.append(['Source Workspace Path',
                 'Feature Class Name', 'Output DataSet Name/Alias',
                 'Fields to exclude or None',
                 'Formats to Export to', 'Geodatabase Version',
                 'Export Only/Publish Only/Both', 'Production/Test', 'Log Info Level'])
				 
Example:
    files.append([r"F:\Databases\ArcGIS_SDE_Connections\pg_gilpincounty.sde",
                 'SiteAddressPoint', 'AddressPoints',
                 'notes',
                 'shp,dwg,kml,json,csv,metadata,gdb', '9.3',
                 'ALL', 'PROD', 'INFO'])

	
	
