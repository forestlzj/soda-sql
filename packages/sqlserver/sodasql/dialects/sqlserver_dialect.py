#  Copyright 2020 Soda
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#   http://www.apache.org/licenses/LICENSE-2.0
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
from datetime import date

import pyodbc
import logging
from typing import Union, Optional

from sodasql.exceptions.exceptions import WarehouseConnectionError
from sodasql.scan.dialect import Dialect, SQLSERVER, KEY_WAREHOUSE_TYPE
from sodasql.scan.parser import Parser

"""
Connecting to Microsoft SQL Example with pyodbc

server = '<server>.database.windows.net'
database = '<database>'
username = '<username>'
password = '<password>'
driver= '{ODBC Driver 17 for SQL Server}'


with pyodbc.connect('DRIVER='+driver+';SERVER='+server+';PORT=1433;DATABASE='+database+';UID='+username+';PWD='+ password) as conn:
    with conn.cursor() as cursor:
        cursor.execute("SELECT TOP 3 name, collation_name FROM sys.databases")
        row = cursor.fetchone()
        while row:
            print (str(row[0]) + " " + str(row[1]))
            row = cursor.fetchone()

"""

logger = logging.getLogger(__name__)


class SQLServerDialect(Dialect):

    def __init__(self, parser: Parser = None, type: str = SQLSERVER):
        super().__init__(type)
        if parser:
            self.host = parser.get_str_optional_env('host', 'localhost')
            self.port = parser.get_str_optional_env('port', '1433')
            self.driver = parser.get_str_optional_env('driver', 'ODBC Driver 17 for SQL Server')
            self.username = parser.get_str_required_env('username')
            self.password = parser.get_credential('password')
            self.database = parser.get_str_required_env('database')
            self.schema = parser.get_str_required_env('schema')
            self.trusted_connection = parser.get_bool_optional('trusted_connection', False)

    def default_connection_properties(self, params: dict):
        return {
            KEY_WAREHOUSE_TYPE: SQLSERVER,
            'host': 'localhost',
            'port': '1433',
            'username': 'env_var(SQLSERVER_USERNAME)',
            'password': 'env_var(SQLSERVER_PASSWORD)',
            'database': params.get('database', 'sodasqldb'),
            'schema': 'public'
        }

    def default_env_vars(self, params: dict):
        return {
            'SQLSERVER_USERNAME': params.get('username', 'Eg johndoe'),
            'SQLSERVER_PASSWORD': params.get('password', 'Eg abc123')
        }

    def sql_tables_metadata_query(self, limit: Optional[int] = None, filter: str = None):
        sql = (f"SELECT TABLE_NAME \n"
               f"FROM information_schema.tables \n"
               f"WHERE lower(table_schema)='{self.schema.lower()}'")
        if limit is not None:
            sql += f"\n LIMIT {limit}"
        return sql

    def sql_connection_test(self):
        pass

    def create_connection(self):
        try:
            conn = pyodbc.connect(
                ('Trusted_Connection=NO;' if True else '') +
                'DRIVER={' + 'ODBC Driver 17 for SQL Server' +
                '};SERVER=' + 'localhost' +
                ';PORT=' + '1433' +
                ';DATABASE=' + 'sodasqldb' +
                ';UID=' + 'sa' +
                ';PWD=' + 'yourStrong@@Password')
            return conn
        except Exception as e:
            self.try_to_raise_soda_sql_exception(e)

    def query_table(self, table_name):
        query = f"""
        SELECT *
        FROM {table_name}
        LIMIT 1
        """
        return query

    def sql_test_connection(self) -> Union[Exception, bool]:
        return True

    def sql_columns_metadata_query(self, table_name: str) -> str:
        sql = (f"SELECT column_name, data_type, is_nullable \n"
               f"FROM information_schema.columns \n"
               f"WHERE table_name = '{table_name}'")
        return sql

    def is_text(self, column_type: str):
        return column_type.upper() in ['VARCHAR', 'CHAR', 'TEXT', 'NVARCHAR', 'NCHAR', 'NTEXT']

    def is_number(self, column_type: str):
        return column_type.upper() in ['BIGINT', 'NUMERIC', 'BIT', 'SMALLINT', 'DECIMAL', 'SMALLMONEY',
                                       'INT', 'TINYINT', 'MONEY', 'FLOAT', 'REAL']

    def is_time(self, column_type: str):
        return column_type.upper() in ['DATE', 'DATETIMEOFFSET', 'DATETIME2', 'SMALLDATETIME', 'DATETIME', 'TIME']

    def qualify_table_name(self, table_name: str) -> str:
        if self.schema:
            return f'"{self.schema}"."{table_name}"'
        return f'"{table_name}"'

    def sql_expr_regexp_like(self, expr: str, pattern: str):
        return f"{expr} LIKE '{self.qualify_regex(pattern)}'"

    def sql_expr_length(self, expr):
        return f'LEN({expr})'

    def sql_expr_variance(self, expr: str):
        return f'VAR({expr})'

    def sql_expr_stddev(self, expr: str):
        return f'STDEV({expr})'

    def sql_expr_limit(self, count):
        return f'OFFSET 0 ROWS FETCH NEXT {count} ROWS ONLY'

    def sql_select_with_limit(self, table_name, count):
        return f'SELECT TOP {count} * FROM {table_name}'

    # TODO REGEX not supported by SQL SERVER
    def sql_expr_cast_text_to_number(self, quoted_column_name, validity_format):
        if validity_format == 'number_whole':
            return f"CAST({quoted_column_name} AS {self.data_type_decimal})"
        return "CAST(Replace(Replace(Replace(Replace(numeric_varchar,',', ''), '.', ''), '-', ''), ',', " \
               "'.') AS DECIMAL) "

    def sql_expr_count_conditional(self, condition: str, column):
        if "^\\s*$" in condition:
            return f'COUNT (CASE WHEN ltrim(rtrim({column})) != \'\' THEN 1 END)'
        elif "^$" in condition:
            regex_empty = '^%$'
            return f'COUNT (CASE WHEN {column} NOT LIKE \'{regex_empty}\' THEN 1 END)'

        elif "'^\-?\d+([\.,]\d+)? ?%$'" in condition:
            return f'COUNT (CASE WHEN {column} LIKE \'[0-9!-]%[%]\' AND {column} NOT LIKE \'%[a-z-A-Z#=@$?/][%]\' ' \
                   f'THEN 1 END)'
        #number_whole
        elif "^\-?[0-9]+$" in condition:
            condition = condition.replace('^\-?[0-9]+$', '[-0-9]%')
            return f'COUNT(CASE WHEN {column} like \'[-0-9]%\' and {column} not like \'[-0-9][.,]%\' THEN 1 END)'
        elif "^\-?[0-9]+,[0-9]+$" in condition:
            condition = condition.replace('^\-?[0-9]+,[0-9]+$', '[-0-9][,0-9]%[0-9]%')
            return f'COUNT(CASE WHEN {condition} THEN 1 END)'
        elif "^\-?[0-9]+\.[0-9]+$" in condition:
            condition = condition.replace('^\-?[0-9]+\.[0-9]+$', '[-0-9][.0-9]%[0-9]%')
            return f'COUNT(CASE WHEN {condition} THEN 1 END)'
        #phone number
        elif "'^((\+[0-9]{1,2}\s)?\(?[0-9]{3}\)?[\s.-])?[0-9]{3}[\s.-][0-9]{4}$'" in condition:
            return f'COUNT(CASE WHEN {column} like \'[+!0-9]%\' and {column} not like \'%[a-z!A-z]\' THEN 1 END)'
        #date_eu
        elif "^([1-9]|0[1-9]|[12][0-9]|3[01])[-\./]([1-9]|0[1-9]|1[012])[-\./](19|20)?[0-9][0-9]" in condition:
            return f'COUNT(CASE WHEN {column} LIKE \'[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]\' OR {column} LIKE \'[0-9][0-9]-[0-9][0-9]-[0-9][0-9][0-9][0-9]\' OR {column} LIKE \'[0-9][0-9].[0-9][0-9].[0-9][0-9][0-9][0-9]\' THEN 1 END)'
        #date_us
        elif "^([1-9]|0[1-9]|1[012])[-\./]([1-9]|0[1-9]|[12][0-9]|3[01])[-\./](19|20)?[0-9][0-9]" in condition:
            return f'COUNT(CASE WHEN {column} LIKE \'[0-9][0-9]/[0-9][0-9]/[0-9][0-9][0-9][0-9]\' OR {column} LIKE \'[0-9][0-9]-[0-9][0-9]-[0-9][0-9][0-9][0-9]\' OR {column} LIKE \'[0-9][0-9].[0-9][0-9].[0-9][0-9][0-9][0-9]\' THEN 1 END)'
        elif "^(19|20)[0-9][0-9][-\./]?([1-9]|0[1-9]|1[012])[-\./]?([1-9]|0[1-9]|[12][0-9]|3[01])" in condition:
            return f'COUNT(CASE WHEN {column} LIKE \'[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9]\' OR {column} LIKE \'[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]\' OR {column} LIKE \'[0-9][0-9][0-9][0-9].[0-9][0-9].[0-9][0-9]\' THEN 1 END)'
        #time
        elif "([0-9]|1[0-9]|2[0-4])[:-]([0-9]|[0-5][0-9])([:-]([0-9]|[0-5][0-9])(,[0-9]+)?)?$" in condition:
            return f'COUNT(CASE WHEN {column} LIKE \'%[010-9!20-3]:[0-5][0-9]%\' OR {column} LIKE \'%[010-9!20-3]-[0-5][0-9]%\' THEN 1 END)'
        #ip_address
        #TODO: find a better way to do this, way too much combinations to fit in SQLServer regex
        elif "^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$" in condition:
            return f'COUNT(CASE WHEN {column} LIKE \'[0-9]%.%\' and {column} like \'[0-9].[0-9].[0-9].[0-9]\'  or {column} like \'[0-9][0-9].%\' or {column} like \'[0-9][0-9][0-9].%\' or {column} like \'[0-9][0-9][0-9].%\' THEN 1 END)'
        #uuid
        elif "^[0-9a-fA-F]{8}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{4}\-[0-9a-fA-F]{12}$" in condition:
            return f'COUNT(CASE WHEN {column} LIKE \'[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]\' THEN 1 END)'
        else:
            return f'COUNT(CASE WHEN {condition} THEN 1 END)'
