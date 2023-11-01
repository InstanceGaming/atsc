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
