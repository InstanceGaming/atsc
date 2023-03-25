from typing import Optional


CONFIG_SCHEMA_VERSION = 3


def validate_dynamic_controller(config: dict, version: int) -> Optional[str]:
    if version != CONFIG_SCHEMA_VERSION:
        raise ValueError('unknown version {} for dynamic inspection', version)

    # todo: add many many more test cases here

    for n, phase_node in enumerate(config['phases'], start=1):
        defines_ped_ls = phase_node['load-switches'].get('ped') is not None
        ped_clr_enable = phase_node['pclr-enable']
        if ped_clr_enable and not defines_ped_ls:
            return f'phase {n} has pclr enabled but no ped load switch defined'

    return None
