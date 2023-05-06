from typing import Optional


CONFIG_SCHEMA_VERSION = 4


def validate_dynamic_controller(config: dict, version: int) -> Optional[str]:
    if version != CONFIG_SCHEMA_VERSION:
        raise ValueError('unknown version {} for dynamic inspection', version)

    # todo: add many many more test cases here

    return None
