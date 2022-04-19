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

from logging import Filter, Logger, addLevelName, setLoggerClass


VERBOSE = 8
FINE = 6
BUS = 4
SORTING = 2


addLevelName(VERBOSE, 'VERBOSE')
addLevelName(FINE, 'FINE')
addLevelName(BUS, 'BUS')
addLevelName(SORTING, 'SORTING')


class FineLogger(Logger):
    """
    A more detailed logging facility with three new levels:
    verbose, fine and bus.
    """

    def __init__(self, name: str):
        super().__init__(name)

    def verbose(self, msg: str, *args, **kwargs):
        if self.isEnabledFor(VERBOSE):
            self._log(VERBOSE, msg, args, **kwargs)

    def fine(self, msg: str, *args, **kwargs):
        if self.isEnabledFor(FINE):
            self._log(FINE, msg, args, **kwargs)

    def bus(self, msg: str, *args, **kwargs):
        if self.isEnabledFor(BUS):
            self._log(BUS, msg, args, **kwargs)

    def sorting(self, msg: str, *args, **kwargs):
        if self.isEnabledFor(SORTING):
            self._log(SORTING, msg, args, **kwargs)


def set_default():
    """
    Make the FineLogger class default type for new loggers.
    """
    setLoggerClass(FineLogger)


set_default()
