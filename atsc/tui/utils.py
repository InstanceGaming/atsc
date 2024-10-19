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
from rich.text import Text
from grpclib.metadata import Deadline
from atsc.common.constants import FLOAT_PRECISION_TIME


def boolean_text(condition: bool,
                 value1,
                 style1: str,
                 value2,
                 style2: str):
    if condition:
        return Text(str(value1), style=style1)
    else:
        return Text(str(value2), style=style2)


def text_or_dash(condition: bool, txt: str, txt_style: str):
    return boolean_text(condition, txt, txt_style, '-', 'bright_black')


def get_time_text(v: float, force_style=None):
    rounded = round(v, FLOAT_PRECISION_TIME)
    text = Text(format(rounded, '.1f'))
    if v < 0.0:
        color = 'red'
    else:
        color = 'white'
    text.stylize(force_style or color)
    return text


def combine_texts_new_line(*texts) -> Text:
    text = texts[0]
    for i in range(1, len(texts)):
        text = text.append('\n')
        if i < len(texts):
            text = text.append_text(texts[i])
    return text


def deadline_from_timeout(timeout: float | None):
    if timeout is None:
        return None
    return Deadline.from_timeout(timeout)
