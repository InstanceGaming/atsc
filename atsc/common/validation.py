#  Copyright 2022 Jacob Jewett
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import os
import enum
import json
import jsonschema
from typing import List, Iterable
from jsonschema import SchemaError, ValidationError
from collections import ChainMap
from dateutil.parser import parse as dt_parse


class FileSchemaErrorType(enum.Enum):
    NO_PATHS = 1
    NOT_FOUND = 2
    CANNOT_READ = 3
    BAD_SYNTAX = 4
    NO_VERSION = 5
    MIXING_VERSIONS = 6
    UNKNOWN_VERSION = 7
    DUPLICATE_ROOT_NODE = 8
    INVALID_BY_SCHEMA = 9
    SCHEMA_INVALID = 10


class FileSchemaError(Exception):

    @property
    def generic_error(self):
        return self._error

    @property
    def details(self):
        return self._details

    def __init__(self, generic_error: FileSchemaErrorType, **details):
        self._error = generic_error
        self._details = details


class FileSchemaValidator:

    @property
    def version(self):
        return self._version

    def __init__(self, config_schema: str, known_versions: Iterable):
        self._schema_path = config_schema

        with open(config_schema, 'r') as sf:
            self._schema = json.load(sf)

        self._known_versions = known_versions
        self._version = None

    def load(self, paths: List[os.PathLike]) -> dict:
        cm = ChainMap()

        if len(paths) > 0:
            for path in paths:
                if not os.path.exists(path):
                    raise FileSchemaError(FileSchemaErrorType.NOT_FOUND,
                                          file=path)
                try:
                    with open(path, 'r') as f:
                        file_data = json.load(f)
                        file_version = file_data.get('version')

                        if file_version is None:
                            raise FileSchemaError(
                                FileSchemaErrorType.NO_VERSION,
                                file=path
                            )

                        if self._version is not None and \
                                file_version != self._version:
                            raise FileSchemaError(
                                FileSchemaErrorType.MIXING_VERSIONS,
                                file=path
                            )
                        else:
                            if file_version not in self._known_versions:
                                raise FileSchemaError(
                                    FileSchemaErrorType.UNKNOWN_VERSION,
                                    file=path
                                )

                            self._version = file_version

                        for root_node in file_data.keys():
                            if root_node in cm.keys():
                                raise FileSchemaError(
                                    FileSchemaErrorType.DUPLICATE_ROOT_NODE,
                                    file=path,
                                    node_name=root_node
                                )

                        cm.update(file_data)
                except OSError as e:
                    raise FileSchemaError(FileSchemaErrorType.CANNOT_READ,
                                          file=path,
                                          underlying=e)
        else:
            raise FileSchemaError(FileSchemaErrorType.NO_PATHS)

        final_data = dict(cm)

        try:
            jsonschema.validate(final_data, self._schema)
        except SchemaError as e:
            raise FileSchemaError(FileSchemaErrorType.SCHEMA_INVALID,
                                  message=e.message)
        except ValidationError as e:
            raise FileSchemaError(FileSchemaErrorType.INVALID_BY_SCHEMA,
                                  message=e.message,
                                  validator=e.validator_value,
                                  node_path=e.json_path)

        return final_data


def validate_time_text(text):
    try:
        dt_parse(text, fuzzy=True, ignoretz=True)
        return True
    except ValueError:
        return False
