# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: controller.proto
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder


# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(
    b'\n\x10\x63ontroller.proto\x12\x04\x61tsc\"3\n\x10LoadSwitchUpdate\x12\t'
    b'\n\x01\x61\x18\x01 \x01(\x08\x12\t\n\x01\x62\x18\x02 \x01('
    b'\x08\x12\t\n\x01\x63\x18\x03 \x01('
    b'\x08\"\xcc\x01\n\x0bPhaseUpdate\x12!\n\x06status\x18\x01 \x01('
    b'\x0e\x32\x11.atsc.PhaseStatus\x12\x13\n\x0bped_service\x18\x02 \x01('
    b'\x08\x12\x1f\n\x05state\x18\x03 \x01('
    b'\x0e\x32\x10.atsc.PhaseState\x12\x12\n\ntime_upper\x18\x04 \x01('
    b'\x02\x12\x12\n\ntime_lower\x18\x05 \x01('
    b'\x02\x12\x12\n\ndetections\x18\x06 \x01('
    b'\r\x12\x15\n\rvehicle_calls\x18\x07 \x01('
    b'\r\x12\x11\n\tped_calls\x18\x08 \x01(\r\"U\n\rControlUpdate\x12 '
    b'\n\x05phase\x18\x02 \x03('
    b'\x0b\x32\x11.atsc.PhaseUpdate\x12\"\n\x02ls\x18\x03 \x03('
    b'\x0b\x32\x16.atsc.LoadSwitchUpdate\"i\n\tPhaseInfo\x12#\n\nflash_mode'
    b'\x18\x01 \x01(\x0e\x32\x0f.atsc.FlashMode\x12\x13\n\x0b\x66ya_setting'
    b'\x18\x02 \x01(\x11\x12\x12\n\nvehicle_ls\x18\x03 \x01('
    b'\r\x12\x0e\n\x06ped_ls\x18\x04 \x01('
    b'\r\"M\n\x0b\x43ontrolInfo\x12\x0f\n\x07version\x18\x01 \x02('
    b'\r\x12\x0c\n\x04name\x18\x02 \x01(\t\x12\x1f\n\x06phases\x18\x08 \x03('
    b'\x0b\x32\x0f.atsc.PhaseInfo*l\n\nPhaseState\x12\x08\n\x04STOP\x10\x00'
    b'\x12\x0c\n\x08MIN_STOP\x10\x02\x12\x08\n\x04RCLR\x10\x04\x12\x0b\n\x07'
    b'\x43\x41UTION\x10\x06\x12\n\n\x06\x45XTEND\x10\x08\x12\x06\n\x02GO\x10'
    b'\n\x12\x08\n\x04PCLR\x10\x0c\x12\x08\n\x04WALK\x10\x0e\x12\x07\n\x03'
    b'\x46YA\x10\x10*@\n\x0bPhaseStatus\x12\x0c\n\x08INACTIVE\x10\x00\x12\x08'
    b'\n\x04NEXT\x10\x01\x12\n\n\x06LEADER\x10\x02\x12\r\n\tSECONDARY\x10\x03'
    b'* \n\tFlashMode\x12\x07\n\x03RED\x10\x01\x12\n\n\x06YELLOW\x10\x02')

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'controller_pb2', globals())
if _descriptor._USE_C_DESCRIPTORS == False:

    DESCRIPTOR._options = None
    _PHASESTATE._serialized_start = 559
    _PHASESTATE._serialized_end = 667
    _PHASESTATUS._serialized_start = 669
    _PHASESTATUS._serialized_end = 733
    _FLASHMODE._serialized_start = 735
    _FLASHMODE._serialized_end = 767
    _LOADSWITCHUPDATE._serialized_start = 26
    _LOADSWITCHUPDATE._serialized_end = 77
    _PHASEUPDATE._serialized_start = 80
    _PHASEUPDATE._serialized_end = 284
    _CONTROLUPDATE._serialized_start = 286
    _CONTROLUPDATE._serialized_end = 371
    _PHASEINFO._serialized_start = 373
    _PHASEINFO._serialized_end = 478
    _CONTROLINFO._serialized_start = 480
    _CONTROLINFO._serialized_end = 557
# @@protoc_insertion_point(module_scope)
