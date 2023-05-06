import re
from functools import partialmethod
from typing import Optional

import loguru


QUENCH_LOG_EXCEPTIONS = True
LOG_LEVEL_PATTERN = re.compile(r'([a-z_]+|\d+)', flags=re.IGNORECASE)


def parse_log_level_argument(arg: Optional[str]) -> dict:
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
    l.level('SORT', no=1, color='<d>')
    l.__class__.sort = partialmethod(l.__class__.log, 'SORT')
    l.level('BUS', no=2, color='<d>')
    l.__class__.bus = partialmethod(l.__class__.log, 'BUS')
    l.level('NET', no=3, color='<d>')
    l.__class__.net = partialmethod(l.__class__.log, 'NET')
    l.level('FIELD', no=4, color='<d>')
    l.__class__.field = partialmethod(l.__class__.log, 'FIELD')
    l.level('VERB', no=7, color='<c>')
    l.__class__.verb = partialmethod(l.__class__.log, 'VERB')


def configure_logger(sink,
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

    fmt = '<level>{level: >8}</level>: {message}'
    if timestamp:
        fmt = '[{time:YYYY-MM-DD hh:mm:ss A}] ' + fmt
    if __debug__:
        fmt += ' <d>[<i>{file}:{line}</i>]</d>'
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
