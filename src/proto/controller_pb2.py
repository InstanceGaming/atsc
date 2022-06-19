# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: controller.proto
"""Generated protocol buffer code."""
from google.protobuf.internal import enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor.FileDescriptor(
  name='controller.proto',
  package='atsc',
  syntax='proto2',
  serialized_options=None,
  create_key=_descriptor._internal_create_key,
  serialized_pb=b'\n\x10\x63ontroller.proto\x12\x04\x61tsc\"3\n\x10LoadSwitchUpdate\x12\t\n\x01\x61\x18\x01 \x01(\x08\x12\t\n\x01\x62\x18\x02 \x01(\x08\x12\t\n\x01\x63\x18\x03 \x01(\x08\"\xcc\x01\n\x0bPhaseUpdate\x12!\n\x06status\x18\x01 \x01(\x0e\x32\x11.atsc.PhaseStatus\x12\x13\n\x0bped_service\x18\x02 \x01(\x08\x12\x1f\n\x05state\x18\x03 \x01(\x0e\x32\x10.atsc.PhaseState\x12\x12\n\ntime_upper\x18\x04 \x01(\x02\x12\x12\n\ntime_lower\x18\x05 \x01(\x02\x12\x12\n\ndetections\x18\x06 \x01(\r\x12\x15\n\rvehicle_calls\x18\x07 \x01(\r\x12\x11\n\tped_calls\x18\x08 \x01(\r\"U\n\rControlUpdate\x12 \n\x05phase\x18\x02 \x03(\x0b\x32\x11.atsc.PhaseUpdate\x12\"\n\x02ls\x18\x03 \x03(\x0b\x32\x16.atsc.LoadSwitchUpdate\"i\n\tPhaseInfo\x12#\n\nflash_mode\x18\x01 \x01(\x0e\x32\x0f.atsc.FlashMode\x12\x13\n\x0b\x66ya_setting\x18\x02 \x01(\x11\x12\x12\n\nvehicle_ls\x18\x03 \x01(\r\x12\x0e\n\x06ped_ls\x18\x04 \x01(\r\"M\n\x0b\x43ontrolInfo\x12\x0f\n\x07version\x18\x01 \x02(\r\x12\x0c\n\x04name\x18\x02 \x01(\t\x12\x1f\n\x06phases\x18\x08 \x03(\x0b\x32\x0f.atsc.PhaseInfo*l\n\nPhaseState\x12\x08\n\x04STOP\x10\x00\x12\x11\n\rRED_CLEARANCE\x10\x01\x12\x0b\n\x07\x43\x41UTION\x10\x02\x12\n\n\x06\x45XTEND\x10\x03\x12\x06\n\x02GO\x10\x04\x12\r\n\tPED_CLEAR\x10\x05\x12\x08\n\x04WALK\x10\x06\x12\x07\n\x03\x46YA\x10\x07*@\n\x0bPhaseStatus\x12\x0c\n\x08INACTIVE\x10\x00\x12\x08\n\x04NEXT\x10\x01\x12\n\n\x06LEADER\x10\x02\x12\r\n\tSECONDARY\x10\x03* \n\tFlashMode\x12\x07\n\x03RED\x10\x01\x12\n\n\x06YELLOW\x10\x02'
)

_PHASESTATE = _descriptor.EnumDescriptor(
  name='PhaseState',
  full_name='atsc.PhaseState',
  filename=None,
  file=DESCRIPTOR,
  create_key=_descriptor._internal_create_key,
  values=[
    _descriptor.EnumValueDescriptor(
      name='STOP', index=0, number=0,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(
      name='RED_CLEARANCE', index=1, number=1,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(
      name='CAUTION', index=2, number=2,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(
      name='EXTEND', index=3, number=3,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(
      name='GO', index=4, number=4,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(
      name='PED_CLEAR', index=5, number=5,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(
      name='WALK', index=6, number=6,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(
      name='FYA', index=7, number=7,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
  ],
  containing_type=None,
  serialized_options=None,
  serialized_start=559,
  serialized_end=667,
)
_sym_db.RegisterEnumDescriptor(_PHASESTATE)

PhaseState = enum_type_wrapper.EnumTypeWrapper(_PHASESTATE)
_PHASESTATUS = _descriptor.EnumDescriptor(
  name='PhaseStatus',
  full_name='atsc.PhaseStatus',
  filename=None,
  file=DESCRIPTOR,
  create_key=_descriptor._internal_create_key,
  values=[
    _descriptor.EnumValueDescriptor(
      name='INACTIVE', index=0, number=0,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(
      name='NEXT', index=1, number=1,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(
      name='LEADER', index=2, number=2,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(
      name='SECONDARY', index=3, number=3,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
  ],
  containing_type=None,
  serialized_options=None,
  serialized_start=669,
  serialized_end=733,
)
_sym_db.RegisterEnumDescriptor(_PHASESTATUS)

PhaseStatus = enum_type_wrapper.EnumTypeWrapper(_PHASESTATUS)
_FLASHMODE = _descriptor.EnumDescriptor(
  name='FlashMode',
  full_name='atsc.FlashMode',
  filename=None,
  file=DESCRIPTOR,
  create_key=_descriptor._internal_create_key,
  values=[
    _descriptor.EnumValueDescriptor(
      name='RED', index=0, number=1,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
    _descriptor.EnumValueDescriptor(
      name='YELLOW', index=1, number=2,
      serialized_options=None,
      type=None,
      create_key=_descriptor._internal_create_key),
  ],
  containing_type=None,
  serialized_options=None,
  serialized_start=735,
  serialized_end=767,
)
_sym_db.RegisterEnumDescriptor(_FLASHMODE)

FlashMode = enum_type_wrapper.EnumTypeWrapper(_FLASHMODE)
STOP = 0
RED_CLEARANCE = 1
CAUTION = 2
EXTEND = 3
GO = 4
PED_CLEAR = 5
WALK = 6
FYA = 7
INACTIVE = 0
NEXT = 1
LEADER = 2
SECONDARY = 3
RED = 1
YELLOW = 2



_LOADSWITCHUPDATE = _descriptor.Descriptor(
  name='LoadSwitchUpdate',
  full_name='atsc.LoadSwitchUpdate',
  filename=None,
  file=DESCRIPTOR,
  containing_type=None,
  create_key=_descriptor._internal_create_key,
  fields=[
    _descriptor.FieldDescriptor(
      name='a', full_name='atsc.LoadSwitchUpdate.a', index=0,
      number=1, type=8, cpp_type=7, label=1,
      has_default_value=False, default_value=False,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='b', full_name='atsc.LoadSwitchUpdate.b', index=1,
      number=2, type=8, cpp_type=7, label=1,
      has_default_value=False, default_value=False,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='c', full_name='atsc.LoadSwitchUpdate.c', index=2,
      number=3, type=8, cpp_type=7, label=1,
      has_default_value=False, default_value=False,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
  ],
  extensions=[
  ],
  nested_types=[],
  enum_types=[
  ],
  serialized_options=None,
  is_extendable=False,
  syntax='proto2',
  extension_ranges=[],
  oneofs=[
  ],
  serialized_start=26,
  serialized_end=77,
)


_PHASEUPDATE = _descriptor.Descriptor(
  name='PhaseUpdate',
  full_name='atsc.PhaseUpdate',
  filename=None,
  file=DESCRIPTOR,
  containing_type=None,
  create_key=_descriptor._internal_create_key,
  fields=[
    _descriptor.FieldDescriptor(
      name='status', full_name='atsc.PhaseUpdate.status', index=0,
      number=1, type=14, cpp_type=8, label=1,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='ped_service', full_name='atsc.PhaseUpdate.ped_service', index=1,
      number=2, type=8, cpp_type=7, label=1,
      has_default_value=False, default_value=False,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='state', full_name='atsc.PhaseUpdate.state', index=2,
      number=3, type=14, cpp_type=8, label=1,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='time_upper', full_name='atsc.PhaseUpdate.time_upper', index=3,
      number=4, type=2, cpp_type=6, label=1,
      has_default_value=False, default_value=float(0),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='time_lower', full_name='atsc.PhaseUpdate.time_lower', index=4,
      number=5, type=2, cpp_type=6, label=1,
      has_default_value=False, default_value=float(0),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='detections', full_name='atsc.PhaseUpdate.detections', index=5,
      number=6, type=13, cpp_type=3, label=1,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='vehicle_calls', full_name='atsc.PhaseUpdate.vehicle_calls', index=6,
      number=7, type=13, cpp_type=3, label=1,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='ped_calls', full_name='atsc.PhaseUpdate.ped_calls', index=7,
      number=8, type=13, cpp_type=3, label=1,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
  ],
  extensions=[
  ],
  nested_types=[],
  enum_types=[
  ],
  serialized_options=None,
  is_extendable=False,
  syntax='proto2',
  extension_ranges=[],
  oneofs=[
  ],
  serialized_start=80,
  serialized_end=284,
)


_CONTROLUPDATE = _descriptor.Descriptor(
  name='ControlUpdate',
  full_name='atsc.ControlUpdate',
  filename=None,
  file=DESCRIPTOR,
  containing_type=None,
  create_key=_descriptor._internal_create_key,
  fields=[
    _descriptor.FieldDescriptor(
      name='phase', full_name='atsc.ControlUpdate.phase', index=0,
      number=2, type=11, cpp_type=10, label=3,
      has_default_value=False, default_value=[],
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='ls', full_name='atsc.ControlUpdate.ls', index=1,
      number=3, type=11, cpp_type=10, label=3,
      has_default_value=False, default_value=[],
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
  ],
  extensions=[
  ],
  nested_types=[],
  enum_types=[
  ],
  serialized_options=None,
  is_extendable=False,
  syntax='proto2',
  extension_ranges=[],
  oneofs=[
  ],
  serialized_start=286,
  serialized_end=371,
)


_PHASEINFO = _descriptor.Descriptor(
  name='PhaseInfo',
  full_name='atsc.PhaseInfo',
  filename=None,
  file=DESCRIPTOR,
  containing_type=None,
  create_key=_descriptor._internal_create_key,
  fields=[
    _descriptor.FieldDescriptor(
      name='flash_mode', full_name='atsc.PhaseInfo.flash_mode', index=0,
      number=1, type=14, cpp_type=8, label=1,
      has_default_value=False, default_value=1,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='fya_setting', full_name='atsc.PhaseInfo.fya_setting', index=1,
      number=2, type=17, cpp_type=1, label=1,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='vehicle_ls', full_name='atsc.PhaseInfo.vehicle_ls', index=2,
      number=3, type=13, cpp_type=3, label=1,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='ped_ls', full_name='atsc.PhaseInfo.ped_ls', index=3,
      number=4, type=13, cpp_type=3, label=1,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
  ],
  extensions=[
  ],
  nested_types=[],
  enum_types=[
  ],
  serialized_options=None,
  is_extendable=False,
  syntax='proto2',
  extension_ranges=[],
  oneofs=[
  ],
  serialized_start=373,
  serialized_end=478,
)


_CONTROLINFO = _descriptor.Descriptor(
  name='ControlInfo',
  full_name='atsc.ControlInfo',
  filename=None,
  file=DESCRIPTOR,
  containing_type=None,
  create_key=_descriptor._internal_create_key,
  fields=[
    _descriptor.FieldDescriptor(
      name='version', full_name='atsc.ControlInfo.version', index=0,
      number=1, type=13, cpp_type=3, label=2,
      has_default_value=False, default_value=0,
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='name', full_name='atsc.ControlInfo.name', index=1,
      number=2, type=9, cpp_type=9, label=1,
      has_default_value=False, default_value=b"".decode('utf-8'),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
    _descriptor.FieldDescriptor(
      name='phases', full_name='atsc.ControlInfo.phases', index=2,
      number=8, type=11, cpp_type=10, label=3,
      has_default_value=False, default_value=[],
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      serialized_options=None, file=DESCRIPTOR,  create_key=_descriptor._internal_create_key),
  ],
  extensions=[
  ],
  nested_types=[],
  enum_types=[
  ],
  serialized_options=None,
  is_extendable=False,
  syntax='proto2',
  extension_ranges=[],
  oneofs=[
  ],
  serialized_start=480,
  serialized_end=557,
)

_PHASEUPDATE.fields_by_name['status'].enum_type = _PHASESTATUS
_PHASEUPDATE.fields_by_name['state'].enum_type = _PHASESTATE
_CONTROLUPDATE.fields_by_name['phase'].message_type = _PHASEUPDATE
_CONTROLUPDATE.fields_by_name['ls'].message_type = _LOADSWITCHUPDATE
_PHASEINFO.fields_by_name['flash_mode'].enum_type = _FLASHMODE
_CONTROLINFO.fields_by_name['phases'].message_type = _PHASEINFO
DESCRIPTOR.message_types_by_name['LoadSwitchUpdate'] = _LOADSWITCHUPDATE
DESCRIPTOR.message_types_by_name['PhaseUpdate'] = _PHASEUPDATE
DESCRIPTOR.message_types_by_name['ControlUpdate'] = _CONTROLUPDATE
DESCRIPTOR.message_types_by_name['PhaseInfo'] = _PHASEINFO
DESCRIPTOR.message_types_by_name['ControlInfo'] = _CONTROLINFO
DESCRIPTOR.enum_types_by_name['PhaseState'] = _PHASESTATE
DESCRIPTOR.enum_types_by_name['PhaseStatus'] = _PHASESTATUS
DESCRIPTOR.enum_types_by_name['FlashMode'] = _FLASHMODE
_sym_db.RegisterFileDescriptor(DESCRIPTOR)

LoadSwitchUpdate = _reflection.GeneratedProtocolMessageType('LoadSwitchUpdate', (_message.Message,), {
  'DESCRIPTOR' : _LOADSWITCHUPDATE,
  '__module__' : 'controller_pb2'
  # @@protoc_insertion_point(class_scope:atsc.LoadSwitchUpdate)
  })
_sym_db.RegisterMessage(LoadSwitchUpdate)

PhaseUpdate = _reflection.GeneratedProtocolMessageType('PhaseUpdate', (_message.Message,), {
  'DESCRIPTOR' : _PHASEUPDATE,
  '__module__' : 'controller_pb2'
  # @@protoc_insertion_point(class_scope:atsc.PhaseUpdate)
  })
_sym_db.RegisterMessage(PhaseUpdate)

ControlUpdate = _reflection.GeneratedProtocolMessageType('ControlUpdate', (_message.Message,), {
  'DESCRIPTOR' : _CONTROLUPDATE,
  '__module__' : 'controller_pb2'
  # @@protoc_insertion_point(class_scope:atsc.ControlUpdate)
  })
_sym_db.RegisterMessage(ControlUpdate)

PhaseInfo = _reflection.GeneratedProtocolMessageType('PhaseInfo', (_message.Message,), {
  'DESCRIPTOR' : _PHASEINFO,
  '__module__' : 'controller_pb2'
  # @@protoc_insertion_point(class_scope:atsc.PhaseInfo)
  })
_sym_db.RegisterMessage(PhaseInfo)

ControlInfo = _reflection.GeneratedProtocolMessageType('ControlInfo', (_message.Message,), {
  'DESCRIPTOR' : _CONTROLINFO,
  '__module__' : 'controller_pb2'
  # @@protoc_insertion_point(class_scope:atsc.ControlInfo)
  })
_sym_db.RegisterMessage(ControlInfo)


# @@protoc_insertion_point(module_scope)
