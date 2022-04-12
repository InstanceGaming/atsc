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
import logging
import jsonschema
from typing import List
from jsonschema import SchemaError, ValidationError
from collections import ChainMap
from dateutil.parser import parse as dt_parse


CONFIG_SCHEMA_VERSION = 2


class ErrorType(enum.Enum):
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


class ConfigError(Exception):

    @property
    def generic_error(self):
        return self._error

    @property
    def details(self):
        return self._details

    def __init__(self, generic_error: ErrorType, **details):
        self._error = generic_error
        self._details = details


class ConfigValidator:
    LOG = logging.getLogger('atsc.validator')

    @property
    def version(self):
        return self._version

    def __init__(self, config_schema: str):
        self._schema_path = config_schema

        with open(config_schema, 'r') as sf:
            self._schema = json.load(sf)

        self._version = None

    def load(self, paths: List[str]) -> dict:
        cm = ChainMap()

        if len(paths) > 0:
            for path in paths:
                if not os.path.exists(path):
                    raise ConfigError(ErrorType.NOT_FOUND, file=path)
                try:
                    with open(path, 'r') as f:
                        file_data = json.load(f)
                        file_version = file_data.get('version')

                        if file_version is None:
                            raise ConfigError(ErrorType.NO_VERSION,
                                              file=path)
                        else:
                            del file_data['version']

                        if self._version is not None and \
                                file_version != self._version:
                            raise ConfigError(ErrorType.MIXING_VERSIONS,
                                              file=path)
                        else:
                            if file_version != CONFIG_SCHEMA_VERSION:
                                raise ConfigError(ErrorType.UNKNOWN_VERSION,
                                                  file=path)

                            self._version = file_version

                        for root_node in file_data.keys():
                            if root_node in cm.keys():
                                raise ConfigError(ErrorType.DUPLICATE_ROOT_NODE,
                                                  file=path,
                                                  node_name=root_node)

                        cm.update(file_data)
                except OSError as e:
                    raise ConfigError(ErrorType.CANNOT_READ,
                                      file=path,
                                      underlying=e)
        else:
            raise ConfigError(ErrorType.NO_PATHS)

        final_data = dict(cm)

        try:
            jsonschema.validate(final_data, self._schema)
        except SchemaError as e:
            raise ConfigError(ErrorType.SCHEMA_INVALID,
                              message=e.message)
        except ValidationError as e:
            raise ConfigError(ErrorType.INVALID_BY_SCHEMA,
                              message=e.message,
                              validator=e.validator_value,
                              node_path=e.json_path)

        return final_data


def get_config_schema_path() -> str:
    entry_script_dir = os.path.abspath(os.path.dirname(__file__))
    config_schema_path = os.path.join(entry_script_dir,
                                      'schema',
                                      'configuration.json')
    return config_schema_path


def validate_time_text(text):
    try:
        dt_parse(text, fuzzy=True, ignoretz=True)
        return True
    except ValueError:
        return False


def validate_config_dynamic(config: dict, version: int):
    if version != CONFIG_SCHEMA_VERSION:
        raise ValueError(f'unknown version {version} for dynamic inspection')

    from core import IntervalType

    gib = config['global-interval-bounds']

    if len(gib) != len(IntervalType):
        return 'mismatched GIB key count'

    channels = config['channels']
    channel_count = len(channels)

    if channel_count < 2:
        return 'less than two channels defined'

    schedule_names = []
    for sch in config['schedules']:
        name = sch['name']

        if name in schedule_names:
            return f'duplicate schedule name "{name}"'

        for i, b in enumerate(sch['blocks'], start=1):
            start = b['start']
            if not validate_time_text(start):
                return f'schedule "{name}" has unintelligible start ' \
                       f'value "{start}" (block {i})'

            end = b['end']
            if not validate_time_text(end):
                return f'schedule "{name}" has unintelligible end ' \
                       f'value "{end}" (block {i})'

        schedule_phases = sch['phases']
        schedule_phase_count = len(schedule_phases)

        if schedule_phase_count < 2:
            return f'schedule "{name}" must define at least 2 phases'

        for pi, phase in enumerate(schedule_phases, start=1):
            phase_channels = phase['channels']
            used_indexes_phase = []
            for channel_index in phase_channels:
                if channel_index > channel_count:
                    return f'schedule "{name}" phase {pi} has out-of-bounds ' \
                           'channel index'

                used_indexes_phase.append(channel_index)

        schedule_rings = sch['rings']

        if len(schedule_rings) == 0:
            return f'schedule "{name}" must define at least 1 ring'

        schedule_barriers = sch['barriers']

        if len(schedule_barriers) == 0:
            return f'schedule "{name}" must define at least 1 barrier'

        schedule_names.append(name)

    return None
