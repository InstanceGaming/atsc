#  Copyright 2024 Jacob Jewett
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
import json
from typing import Set, TextIO, Iterable
from pydantic import BaseModel


class TrafficOptions(BaseModel):
    enable: bool
    recycle: bool


class ControlMode(BaseModel):
    startup_demand: bool
    vehicles: TrafficOptions
    pedestrians: TrafficOptions


class Configuration(BaseModel):
    name: str
    mode: ControlMode
    load_switches: Set


def load(streams: Iterable[TextIO]) -> Configuration:
    composite = {}
    
    for stream in streams:
        stream.seek(0)
        fragment = json.load(stream)
        composite = composite | fragment
    
    return Configuration(**composite)
