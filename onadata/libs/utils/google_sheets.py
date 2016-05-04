"""
This module contains classes responsible for communicating with
Google Data API and common spreadsheets models.
"""
import gspread
import json
import xlrd
import httplib2
import re

from xml.etree import ElementTree
from gspread import SpreadsheetNotFound, WorksheetNotFound, CellNotFound
from gspread.ns import _ns
from apiclient import discovery
from django.conf import settings
from oauth2client.contrib.django_orm import Storage

from onadata.apps.main.models import TokenStorageModel

from onadata.libs.utils.export_tools import ExportBuilder,\
    dict_to_joined_export
from onadata.libs.utils.common_tags import INDEX, PARENT_INDEX,\
    PARENT_TABLE_NAME
from onadata.libs.utils.common_tags import ID
from onadata.libs.utils.googlesheets_urls import construct_url


def update_row(worksheet, index, values):
    """"Adds a row to the worksheet at the specified index and populates it
    with values. Widens the worksheet if there are more values than columns.
    :param worksheet: The worksheet to be updated.
    :param index: Index of the row to be updated.
    :param values: List of values for the row.
    """
    data_width = len(values)
    if worksheet.col_count < data_width:
        worksheet.resize(cols=data_width)

    cell_list = []
    for i, value in enumerate(values, start=1):
        cell = worksheet.cell(index, i)
        cell.value = value
        cell_list.append(cell)

    worksheet.update_cells(cell_list)


def update_rows(worksheet, index, rows):
    """"Adds a batch of rows to the worksheet at the specified index and
     populates it with values. Widens the worksheet if there are more values
     than columns.
    :param worksheet: The worksheet to be updated.
    :param index: Index of the row to be updated.
    :param rows: List of values for the row.
    """
    for row in rows:
        data_width = len(row)
        if worksheet.col_count < data_width:
            worksheet.resize(cols=data_width)

        cell_list = []
        for i, value in enumerate(row, start=1):
            cell = worksheet.cell(index, i)
            cell.value = value
            cell_list.append(cell)
        index += 1

    worksheet.update_cells(cell_list)


def batch(iterable, n=1):
    l = len(iterable)
    for ndx in range(0, l, n):
        yield iterable[ndx:min(ndx + n, l)]


def xldr_format_value(cell):
    """A helper function to format the value of a cell.
    The xldr stores integers as floats which means that the cell value
    42 in Excel is returned as 42.0 in Python. This function tries to guess
    if the original value was an integer and returns the proper type.
    """
    value = cell.value
    if cell.ctype == xlrd.XL_CELL_NUMBER and int(value) == value:
        value = int(value)
    return value


def get_google_sheet_id(user, title):
    storage = Storage(TokenStorageModel, 'id', user, 'credential')
    google_credentials = storage.get()

    client = SheetsClient.login_with_service_account(google_credentials)

    return client.get_google_sheet_id(title)


class SheetsClient(gspread.client.Client):
    """An instance of this class communicates with Google Data API."""

    AUTH_SCOPE = ' '.join(['https://docs.google.com/feeds/',
                           'https://spreadsheets.google.com/feeds/',
                           'https://www.googleapis.com/auth/drive.file'])

    DRIVE_API_URL = 'https://www.googleapis.com/drive/v2/files'

    def new(self, title):
        headers = {'Content-Type': 'application/json'}
        data = {
            'title': title,
            'mimeType': 'application/vnd.google-apps.spreadsheet',
            'parents': [{'id': self.get_sheets_folder_id(self.auth)}]
        }

        r = self.session.request(
            'POST', SheetsClient.DRIVE_API_URL, headers=headers,
            data=json.dumps(data))
        resp = json.loads(r.content)
        sheet_id = resp['id']
        return self.open_by_key(sheet_id)

    def create_sheet_folder(self, folder_name="onadata"):
        headers = {'Content-Type': 'application/json'}
        data = {
            'title': folder_name,
            'mimeType': 'application/vnd.google-apps.folder'
        }

        r = self.session.request(
            'POST', SheetsClient.DRIVE_API_URL, headers=headers,
            data=json.dumps(data))
        resp = json.loads(r.content)
        return resp['id']

    def get_sheets_folder_id(self, credentials, folder_name="onadata"):
        http = httplib2.Http()
        drive = discovery.build("drive", "v2",
                                http=credentials.authorize(http))

        response = drive.files().list(
            q="title = '{}' and trashed = false".format(folder_name)).execute()

        if len(response.get('items')) > 0:
            return response.get('items')[0].get('id')

        return self.create_sheet_folder(folder_name)

    def get_google_sheet_id(self, title):
        headers = {'Content-Type': 'application/json'}
        data = {
            'title': title,
            'mimeType': 'application/vnd.google-apps.spreadsheet',
            'parents': [{'id': self.get_sheets_folder_id(self.auth)}]
        }

        r = self.session.request(
            'POST', SheetsClient.DRIVE_API_URL, headers=headers,
            data=json.dumps(data))
        resp = json.loads(r.content)
        return resp['id']

    def create_or_get_spreadsheet(self, title):
        try:
            return self.open(title)
        except SpreadsheetNotFound:

            headers = {'Content-Type': 'application/json'}
            data = {
                'title': title,
                'mimeType': 'application/vnd.google-apps.spreadsheet',
                'parents': [{'id': self.get_sheets_folder_id(self.auth)}]
            }

            self.session.request('POST', SheetsClient.DRIVE_API_URL,
                                 headers=headers, data=json.dumps(data))

            return self.open(title)

    def add_service_account_to_spreadsheet(self, spreadsheet):
        url = '%s/%s/permissions' % (SheetsClient.DRIVE_API_URL,
                                     spreadsheet.id)
        headers = {'Content-Type': 'application/json'}
        data = {
            'role': 'writer',
            'type': 'user',
            'value': settings.GOOGLE_CLIENT_EMAIL
        }

        self.session.request(
            'POST', url, headers=headers, data=json.dumps(data))

    @classmethod
    def login_with_service_account(cls, credential=None):
        client = SheetsClient(auth=credential)
        client.login()
        return client

    def get_googlesheet_title(self, spreadsheet_id):
        spreadsheet = self.open_by_key(spreadsheet_id)
        return spreadsheet.title()


class SheetsExportBuilder(ExportBuilder):
    client = None
    spreadsheet = None
    # Worksheets generated by this class.
    worksheets = {}
    # Map of section_names to generated_names
    worksheet_titles = {}
    # The URL of the exported sheet.
    url = None

    # Configuration options
    spreadsheet_title = None
    flatten_repeated_fields = True
    google_credentials = None

    # Constants
    SHEETS_BASE_URL = 'https://docs.google.com/spreadsheet/ccc?key=%s&hl'
    FLATTENED_SHEET_TITLE = 'raw'

    def __init__(self, xform, google_credentials, config):
        """
        Class constructor,
        :param xform:
        :param google_credentials:
        :param config: dict with export settings
               config params: spreadsheet_title defaults to form id_string
                            : flatten_repeated_field default is True
        """
        super(SheetsExportBuilder, self).__init__()

        self.google_credentials = google_credentials

        self.spreadsheet_title = \
            config.get('spreadsheet_title', xform.id_string)
        self.flatten_repeated_fields = \
            config.get('flatten_repeated_fields', True)
        self.set_survey(xform.survey)

    def live_update(self, path, data, xform, spreadsheet_id=None,
                    delete=False, update=False):
        self.client = \
            SheetsClient.login_with_service_account(self.google_credentials)

        if spreadsheet_id:
            self.spreadsheet = self.client.open_by_key(spreadsheet_id)
        else:
            self.spreadsheet = self.client.create_or_get_spreadsheet(
                title=self.spreadsheet_title)

        # Add Service account as editor
        self.client.add_service_account_to_spreadsheet(self.spreadsheet)

        if update:
            return self.update_spreadsheet_row(data, xform)

        if delete:
            return self.delete_row(data, xform)

        value = self.append_spreadsheet_row(data, xform)
        if isinstance(value, bool) and not value:
            self.export_tabular(path, data)

        # Delete the default worksheet if it exists
        # NOTE: for some reason self.spreadsheet.worksheets() does not contain
        #       the default worksheet (Sheet1). We therefore need to fetch an
        #       updated list here.
        feed = self.client.get_worksheets_feed(self.spreadsheet)
        for elem in feed.findall(gspread.ns._ns('entry')):
            ws = gspread.Worksheet(self.spreadsheet, elem)
            if ws.title == 'Sheet1':
                self.client.del_worksheet(ws)

    def export(self, path, data, username, xform=None, filter_query=None):
        self.client = \
            SheetsClient.login_with_service_account(self.google_credentials)

        self.spreadsheet = self.client.new(title=self.spreadsheet_title)

        self.url = self.SHEETS_BASE_URL % self.spreadsheet.id

        # Add Service account as editor
        self.client.add_service_account_to_spreadsheet(self.spreadsheet)

        # Perform the actual export
        if self.flatten_repeated_fields:
            self.export_flattened(path, data, username, xform,
                                  filter_query)
        else:
            self.export_tabular(path, data)

        # Delete the default worksheet if it exists
        # NOTE: for some reason self.spreadsheet.worksheets() does not contain
        #       the default worksheet (Sheet1). We therefore need to fetch an
        #       updated list here.
        feed = self.client.get_worksheets_feed(self.spreadsheet)
        for elem in feed.findall(gspread.ns._ns('entry')):
            ws = gspread.Worksheet(self.spreadsheet, elem)
            if ws.title == 'Sheet1':
                self.client.del_worksheet(ws)

        return self.url

    def export_flattened(self, path, data, username, xform,
                         filter_query=None):
        from onadata.libs.utils.csv_builder import CSVDataFrameBuilder
        import csv
        # Build a flattened CSV
        csv_builder = CSVDataFrameBuilder(
            username, xform.id_string, filter_query)
        csv_builder.export_to(path)

        # Read CSV back in and filter n/a entries
        rows = []
        with open(path) as f:
            reader = csv.reader(f)
            for row in reader:
                filtered_rows = [x if x != 'n/a' else '' for x in row]
                rows.append(filtered_rows)

        # Create a worksheet for flattened data
        num_rows = len(rows)
        if not num_rows:
            return
        num_cols = len(rows[0])
        ws = self.spreadsheet.add_worksheet(
            title=self.FLATTENED_SHEET_TITLE, rows=num_rows, cols=num_cols)

        # Write data row by row
        for index, values in enumerate(rows, 1):
            update_row(ws, index, values)

    def export_tabular(self, path, data):
        # Add worksheets for export.
        self._create_worksheets()

        # Write the headers
        self._insert_headers()

        # Write the data
        self._insert_data(data)

    def _insert_data(self, data, row_index=None):
        """Writes data rows for each section."""
        indices = {}
        survey_name = self.survey.name
        for index, d in enumerate(data, 1):
            joined_export = dict_to_joined_export(
                d, index, indices, survey_name, self.survey, d)
            output = ExportBuilder.decode_mongo_encoded_section_names(
                joined_export)
            # attach meta fields (index, parent_index, parent_table)
            # output has keys for every section
            if survey_name not in output:
                output[survey_name] = {}
            output[survey_name][INDEX] = index
            output[survey_name][PARENT_INDEX] = -1
            for section in self.sections:
                # get data for this section and write to xls
                section_name = section['name']
                fields = [
                    element['xpath'] for element in
                    section['elements']] + self.EXTRA_FIELDS

                ws = self.worksheets[section_name]
                # section might not exist within the output, e.g. data was
                # not provided for said repeat - write test to check this
                row = output.get(section_name, None)
                if type(row) == dict:
                    SheetsExportBuilder.write_row(
                        self.pre_process_row(row, section), ws, fields,
                        self.worksheet_titles, row_index=row_index)
                elif type(row) == list:
                    for child_row in row:
                        SheetsExportBuilder.write_row(
                            self.pre_process_row(child_row, section),
                            ws, fields, self.worksheet_titles,
                            row_index=row_index)

    def _insert_headers(self):
        """Writes headers for each section."""
        for section in self.sections:
            section_name = section['name']
            headers = [
                element['title'] for element in
                section['elements']] + self.EXTRA_FIELDS
            # get the worksheet
            ws = self.worksheets[section_name]
            # Only create headers if there is none
            update_row(ws, index=1, values=headers)

    def _create_worksheets(self):
        """Creates one worksheet per section."""
        for section in self.sections:
            section_name = section['name']
            work_sheet_title = self.get_valid_sheet_name(
                "_".join(section_name.split("/")),
                self.worksheet_titles.values())
            self.worksheet_titles[section_name] = work_sheet_title
            num_cols = len(section['elements']) + len(self.EXTRA_FIELDS)
            try:
                self.worksheets[section_name] = \
                    self.spreadsheet.worksheet(work_sheet_title)
            except WorksheetNotFound:
                self.worksheets[section_name] = self.spreadsheet.add_worksheet(
                    title=work_sheet_title, rows=1, cols=num_cols)

    def update_spreadsheet_row(self, data, xform):
        try:
            self.worksheets[xform.id_string] \
                = self.spreadsheet.worksheet(xform.id_string)
            worksheet = self.worksheets[xform.id_string]

            if data:
                data_id = data[0].get(ID)
                # get the id cell
                regex_text = re.compile('^{}$'.format(data_id))
                id_cell = worksheet.find(regex_text)

                self._insert_data(data, row_index=id_cell.row)
                return True
        except (CellNotFound, WorksheetNotFound):
            return False

    def append_spreadsheet_row(self, data, xform):
        try:
            self.worksheets[xform.id_string] \
                = self.spreadsheet.worksheet(xform.id_string)
            worksheet = self.worksheets[xform.id_string]

            # get the id cell
            id_cell = worksheet.find(ID)

            # retrieve all the ids
            ids_col_list = worksheet.col_values(id_cell.col)
            ids_col_list = [s for s in ids_col_list if s.isdigit()]
            ids_col_list.sort(reverse=True)
            last_id = ids_col_list[0]
            filtered_data = filter(lambda x: x.get(ID) > int(last_id), data)
            if filtered_data:
                self._insert_data(filtered_data)
                return True

        except (CellNotFound, WorksheetNotFound):
            return False

    @classmethod
    def write_row(
            cls, data, worksheet, fields, worksheet_titles, row_index=None):
        # update parent_table with the generated sheet's title
        data[PARENT_TABLE_NAME] = worksheet_titles.get(
            data.get(PARENT_TABLE_NAME))
        values = [data.get(f) for f in fields]
        if row_index:
            update_row(worksheet, row_index, values)
        else:
            worksheet.append_row(values)

    def delete_row(self, data_id, xform):
        try:
            self.worksheets[xform.id_string] \
                = self.spreadsheet.worksheet(xform.id_string)
            worksheet = self.worksheets[xform.id_string]

            regex_text = re.compile('^{}$'.format(data_id))
            id_cell = worksheet.find(regex_text)

            list_rows_url = construct_url('list', worksheet)
            list_response = self.client.session.get(list_rows_url)

            feed = ElementTree.fromstring(list_response.content)

            all_rows = feed.findall(_ns('entry'))

            row_to_delete = all_rows[id_cell.row - 2]
            # get the edit link
            for link in row_to_delete.findall(_ns('link')):
                if link.get('rel') == 'edit':
                    edit_link = link.get('href')

            self.client.session.delete(edit_link)

            return True
        except (CellNotFound, WorksheetNotFound):
            return False
