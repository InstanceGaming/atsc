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


def formatFields(a, b, c, colored=False):
    r = '<r>R</r>' if colored else 'R'
    y = '<y>Y</y>' if colored else 'Y'
    g = '<g>G</g>' if colored else 'G'
    off = '<d>-</d>' if colored else '-'
    first = r if a else off
    second = y if b else off
    third = g if c else off
    return first + second + third


def buildFieldMessage(switches):
    field_text = ''
    for ls in switches:
        ft = formatFields(ls.a, ls.b, ls.c)
        field_text += f'{ls.id:02d}{ft} '
    return field_text
