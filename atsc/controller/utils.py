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
from typing import List, TypeVar, Iterator


C_T = TypeVar('C_T')


def cycle(v: List[C_T], initial=0) -> Iterator[C_T]:
    """
    Repeat the items within list v indefinitely, in order.
    
    - Seamlessly handles v list mutations (not thread-safe).
    - If the initial value is greater than the length of the list
      at the time, the first index will be the modulo of the list length.
    - Also see `itertools.cycler()`.
    """
    i = initial % len(v)
    while True:
        if i == len(v):
            i = 0
        yield v[i]
        i += 1
