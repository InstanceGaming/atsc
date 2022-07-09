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
import functools
from enum import IntEnum
from typing import Type
from logging import Filter, Logger, addLevelName, setLoggerClass


class CustomLogLevels(IntEnum):
    VERBOSE = 8
    FINE = 6
    BUS = 4
    SORTING = 2


FINE_LOG_OMIT_DUPLICATES = True


class DuplicateFilter(Filter):
    __LAST_LOG_ATTR = 'last_log'

    def filter(self, record):
        current_log = (record.module, record.levelno, record.getMessage())
        if current_log != getattr(self, self.__LAST_LOG_ATTR, None):
            setattr(self, self.__LAST_LOG_ATTR, current_log)
            return True
        return False


class FineLogger(Logger):
    """
    A more detailed logging facility with three new levels:
    verbose, fine and bus.
    """

    def __init__(self, name: str):
        super().__init__(name)

        if FINE_LOG_OMIT_DUPLICATES:
            self.addFilter(DuplicateFilter())

    def setLevel(self, v):
        if isinstance(v, CustomLogLevels):
            lvl = v.value
        else:
            lvl = v
        super(FineLogger, self).setLevel(lvl)


def _customLog(self, msg: str, *args, **kwargs):
    lvl = kwargs.pop('__custom_level')
    lvl_index = lvl.value
    if self.isEnabledFor(lvl_index):
        self._log(lvl_index, msg, args, **kwargs)


def registerCustomLevels(klass: Type[Logger]):
    for lvl in CustomLogLevels:
        setattr(klass,
                lvl.name.lower(),
                functools.partialmethod(_customLog, __custom_level=lvl))
        addLevelName(lvl.value, lvl.name)


registerCustomLevels(FineLogger)
setLoggerClass(FineLogger)
