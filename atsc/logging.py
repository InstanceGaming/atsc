import os
import re
import sys
from datetime import timedelta
from functools import partialmethod
from pathlib import Path
from typing import Optional, TypedDict, Union, Tuple
import loguru
from atsc.constants import ExitCode


QUENCH_LOG_EXCEPTIONS = True
LOG_LEVEL_PATTERN = re.compile(r'^([a-z_]+|\d+)(,([a-z_]+|\d+))?$', flags=re.IGNORECASE)


class SinkLevels(TypedDict):
    default: Tuple[int, int]
    stdout: Tuple[int, int]
    stderr: Tuple[int, int]
    file: Tuple[int, int]


def parse_log_level_shorthand(l, arg: Optional[str]) -> SinkLevels:
    def _parse_value(_sink, _l1) -> tuple:
        _re_result = LOG_LEVEL_PATTERN.match(_l1)
        if _re_result is not None:
            def _coerce_number(_l2):
                try:
                    _l2 = int(_l2)
                except ValueError:
                    try:
                        _l2 = l.level(_l2).no
                    except ValueError:
                        raise ValueError(f'unknown logging min_level "{_l2}" for sink "{_sink}"')
                return _l2
            
            lower = _coerce_number(_re_result.group(1))
            upper = _re_result.group(3)
            
            if upper is not None:
                upper = _coerce_number(upper)
                
                if lower >= upper:
                    raise ValueError(f'impossible logging min_level range for sink "{_sink}" ({lower} >= {upper})')
            
            return lower, upper
        else:
            raise ValueError(f'invalid logging min_level "{_l1}" for sink "{_sink}"')
    
    levels = {
        'default': (0, sys.maxsize),
        'stdout': None,
        'stderr': None,
        'file': None
    }
    if arg:
        cleaned = arg.strip()
        default_set = False
        for part in cleaned.split(';'):
            part = part.strip()
            if '=' in part:
                kv_parts = part.split('=')
                key = kv_parts[0]
                
                if key not in levels.keys():
                    raise KeyError(f'unknown logging sink "{key}"')
                
                levels[key] = _parse_value(key, kv_parts[1])
            else:
                if default_set:
                    raise ValueError('default already defined')

                levels['default'] = _parse_value('default', part)
                default_set = True

    default_level = levels.pop('default')
    for k, v in levels.items():
        if v is None:
            levels[k] = default_level
    
    return levels


def register_custom_levels(l):
    klass = l.__class__
    l.level('CLOCKS', no=1, color='<d>')
    klass.clocks = partialmethod(klass.log, 'CLOCKS')
    l.level('TIMING', no=3, color='<d>')
    klass.timing = partialmethod(klass.log, 'TIMING')
    l.level('BUS', no=4, color='<d>')
    klass.bus = partialmethod(klass.log, 'BUS')
    l.level('FIELD', no=6, color='<d>')
    klass.field = partialmethod(klass.log, 'FIELD')
    l.level('VERB', no=7, color='<c>')
    klass.verb = partialmethod(klass.log, 'VERB')


def setup_sink(l,
               sink,
               levels: Tuple[int, Optional[int]],
               color=False,
               timestamp=False,
               backtrace=False,
               rotation=None,
               retention=None,
               compression=None,
               mode='a'):
    fmt = '<level>{level: >8}</level>: {message} '
    if timestamp:
        fmt = '[{time:YYYY-MM-DD hh:mm:ss A}] ' + fmt
    if __debug__:
        fmt += '<d>[<i>{file}:{line}</i>]</d> '
    
    kwargs = {
        'colorize': color,
        'level': levels[0],
        'format': fmt,
        'backtrace': backtrace,
        'catch': QUENCH_LOG_EXCEPTIONS,
    }
    
    max_level = levels[1]
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
    
    bootstrap_logger = loguru.logger
    bootstrap_logger.remove()
    register_custom_levels(bootstrap_logger)
    
    if isinstance(log_levels, str):
        log_levels = parse_log_level_shorthand(bootstrap_logger, log_levels)
    
    stdout_level = log_levels['stdout']
    stderr_level = log_levels['stderr']
    
    try:
        logger = setup_sink(bootstrap_logger,
                            sys.stdout,
                            stdout_level,
                            color=True)
        
        logger = setup_sink(logger,
                            sys.stderr,
                            stderr_level,
                            color=True)
        
        if log_file is not None:
            
            file_level = log_levels['file']
            log_file = Path(log_file)
            try:
                os.makedirs(os.path.dirname(log_file), exist_ok=True)
            except OSError as e:
                logger.error('failed to make directory structure for log file ({})', str(e))
                exit(ExitCode.LOG_FILE_STRUCTURE_FAIL)
            
            logger = setup_sink(logger,
                                log_file,
                                file_level,
                                timestamp=True,
                                backtrace=True,
                                rotation=rotation,
                                retention=retention,
                                compression='gz')
    
    except (ValueError, TypeError) as e:
        print(f'ERROR: failed to create logging facility ({str(e)})', file=sys.stderr)
        if __debug__:
            raise e
        else:
            exit(ExitCode.LOG_FACILITY_FAIL)
    
    logger.info('log levels {}', ', '.join([f'{k}={v}' for k, v in log_levels.items()]))
    
    return logger
