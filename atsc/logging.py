import os
import re
import sys
from datetime import timedelta
from functools import partialmethod
from pathlib import Path
from typing import Optional, TypedDict, Union
import loguru
from atsc.constants import ExitCode


QUENCH_LOG_EXCEPTIONS = True
LOG_LEVEL_PATTERN = re.compile(r'([a-z_]+|\d+)', flags=re.IGNORECASE)


class SinkLevels(TypedDict):
    default: Union[int, str]
    stdout: Union[int, str]
    stderr: Union[int, str]
    file: Union[int, str]


def parse_log_level_shorthand(arg: Optional[str]) -> SinkLevels:
    levels = {
        'default': 0,
        'stdout': None,
        'stderr': None,
        'file': None
    }
    if arg:
        cleaned = arg.strip()
        default_set = False
        for part in cleaned.split(','):
            part = part.strip()
            if '=' in part:
                kv_parts = part.split('=')
                key = kv_parts[0]
                if key not in levels.keys():
                    raise KeyError(f'unknown logging sink "{key}"')
                value = kv_parts[1]
                result = LOG_LEVEL_PATTERN.match(value)
                if result is not None:
                    value = result.group(1)
                else:
                    raise ValueError(f'unknown logging level "{value}" for {key} sink')
                levels[key] = value
            else:
                if default_set:
                    raise ValueError('default already set')

                result = LOG_LEVEL_PATTERN.match(part)
                if result is not None:
                    levels['default'] = result.group(1)
                    default_set = True
                else:
                    raise ValueError(f'unknown logging level "{part}" for default sink')

    for k, v in levels.items():
        if v is not None:
            try:
                levels[k] = int(v)
            except ValueError:
                pass

    default_level = levels['default']
    for k, v in levels.items():
        if k == 'default':
            continue
        if v is None:
            levels[k] = default_level
    return levels


def register_custom_levels(l):
    klass = l.__class__
    l.level('CLOCKS', no=1, color='<d>')
    klass.clocks = partialmethod(klass.log, 'CLOCKS')
    l.level('TIMING', no=3, color='<d>')
    klass.timing = partialmethod(klass.log, 'TIMING')
    l.level('FIELD', no=6, color='<d>')
    klass.field = partialmethod(klass.log, 'FIELD')
    l.level('VERB', no=7, color='<c>')
    klass.verb = partialmethod(klass.log, 'VERB')


def setup_sink(sink,
               level=0,
               max_level=None,
               color=False,
               timestamp=False,
               logger=None,
               backtrace=False,
               rotation=None,
               retention=None,
               compression=None,
               mode='a'):
    l = logger or loguru.logger
    if logger is None:
        l.remove()
        register_custom_levels(l)

    fmt = '<level>{level: >8}</level>: {message} '
    if timestamp:
        fmt = '[{time:YYYY-MM-DD hh:mm:ss A}] ' + fmt
    if __debug__:
        fmt += '<d>[<i>{file}:{line}</i>]</d> '
    # fmt += '<d>{extra}</d>'
    kwargs = {
        'colorize': color,
        'level': level,
        'format': fmt,
        'backtrace': backtrace,
        'catch': QUENCH_LOG_EXCEPTIONS,
    }

    if max_level is not None:
        kwargs.update({'filter': lambda record: record['level'].no < max_level})

    if isinstance(sink, str):
        kwargs.update({
            'rotation': rotation,
            'retention': retention,
            'compression': compression,
            'mode': mode
        })

    l.add(sink, **kwargs)
    return l


def setup_logger(log_levels: Union[SinkLevels, str],
                 log_file: Optional[os.PathLike] = None,
                 rotation: timedelta = timedelta(days=1),
                 retention: timedelta = timedelta(days=7)):
    if isinstance(log_levels, str):
        log_levels = parse_log_level_shorthand(log_levels)
    
    stdout_level = log_levels['stdout']
    stderr_level = log_levels['stderr']
    
    try:
        logger = setup_sink(sys.stdout,
                            level=stdout_level,
                            color=True)
        logger = setup_sink(sys.stderr, level=stderr_level, color=True,
                            logger=logger)
        if log_file is not None:
            file_level = log_levels['file']
            log_file = Path(log_file)
            try:
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
            except OSError as e:
                logger.error('failed to make directory structure for log file ({})', str(e))
                exit(ExitCode.LOG_FILE_STRUCTURE_FAIL)
            logger = setup_sink(log_file,
                                level=file_level,
                                timestamp=True,
                                logger=logger,
                                backtrace=True,
                                rotation=rotation,
                                retention=retention,
                                compression='gz')
    except (ValueError, TypeError) as e:
        print(f'ERROR: failed to create logging facility ({str(e)})', file=sys.stderr)
        exit(ExitCode.LOG_FACILITY_FAIL)
    
    logger.info('log levels {}', ', '.join([f'{k}={v}' for k, v in log_levels.items()]))
    
    return logger
