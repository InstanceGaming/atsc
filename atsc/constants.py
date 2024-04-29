from jacob.logging import CustomLevel


VERSION = '2.0.1'
TIME_BASE = 0.1
WELCOME_MSG = f'Actuated Traffic Signal Controller v{VERSION} by Jacob Jewett'
CONFIG_SCHEMA_CHECK = True
CONFIG_LOGIC_CHECK = True
CUSTOM_LOG_LEVELS = {
    CustomLevel(10, 'bus_tx'),
    CustomLevel(11, 'bus_rx'),
    CustomLevel(12, 'bus'),
    CustomLevel(20, 'net'),
    CustomLevel(25, 'fields'),
    CustomLevel(35, 'verbose'),
    CustomLevel(40, 'debug'),
    CustomLevel(50, 'info'),
    CustomLevel(90, 'warning'),
    CustomLevel(100, 'error'),
    CustomLevel(200, 'critical')
}
DEFAULT_LEVELS = 'debug,warning;stderr=error,critical;file=info,critical'
