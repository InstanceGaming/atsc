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
import loguru
from pathlib import Path
from atsc.common import cli
from atsc.tui.core import TUI
from atsc.common.utils import setup_logger, get_program_dir
from atsc.tui.constants import DEFAULT_APP_STYLESHEET_PATH
from atsc.common.constants import ExitCode


logger = loguru.logger


def create_app():
    cla, root_ap = cli.parse_common_cla('ATSC text-based UI.',
                                        True,
                                        partial=True)
    
    program_dir = get_program_dir()
    default_stylesheet_path = program_dir.joinpath(DEFAULT_APP_STYLESHEET_PATH)
    
    root_ap.add_argument('-s', '--stylesheet',
                         type=Path,
                         default=default_stylesheet_path,
                         dest='stylesheet_path')
    
    extra_cla = vars(root_ap.parse_args())
    stylesheet_path = extra_cla['stylesheet_path']
    
    setup_logger_result = setup_logger(cla.log_levels_notation,
                                       log_file=cla.log_path)
    
    if setup_logger_result != ExitCode.OK:
        return setup_logger_result
    
    return TUI(rpc_address=cla.rpc_address,
              rpc_port=cla.rpc_port,
              stylesheet_path=stylesheet_path,
              dev_mode=__debug__)


app = create_app()


if __name__ == '__main__':
    exit(app.run())
