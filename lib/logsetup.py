"""Logging initializer for kcommit-analysis-pipeline.

Call setup_logging(verbose) once at the start of each stage.
Colorized output is always enabled (ANSI codes are no-ops on non-ANSI terminals).
"""
import logging
import sys

VERBOSE = 0

_LEVEL_COLORS = {
    logging.DEBUG:    '\033[36m',    # cyan
    logging.INFO:     '\033[32m',    # green
    logging.WARNING:  '\033[33m',    # yellow
    logging.ERROR:    '\033[31m',    # red
    logging.CRITICAL: '\033[35m',    # magenta
}
_RESET = '\033[0m'


class _ColorFormatter(logging.Formatter):
    """Formatter that prepends an ANSI colour code based on log level."""

    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, '')
        msg   = super().format(record)
        return f'{color}{msg}{_RESET}' if color else msg


def setup_logging(verbose: int = 0) -> None:
    """Initialize the root logger.

    verbose=0  → WARNING+   (default)
    verbose=1  → INFO+      (-v)
    verbose=2  → DEBUG+     (-vv)

    Color is applied unconditionally via ANSI escape codes.
    """
    global VERBOSE
    VERBOSE = verbose

    if verbose >= 2:
        loglevel = logging.DEBUG
    elif verbose >= 1:
        loglevel = logging.INFO
    else:
        loglevel = logging.WARNING

    fmt = (
        '%(asctime)s.%(msecs)03d %(levelname)-8s %(module)s'
        ' (%(filename)s:%(lineno)d): %(message)s'
        if verbose >= 2 else
        '%(asctime)s.%(msecs)03d %(levelname)-8s %(module)s: %(message)s'
    )

    # Remove any pre-existing handlers so basicConfig takes effect even if
    # another module already triggered logging initialisation.
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_ColorFormatter(fmt, datefmt='%Y%m%d %H:%M:%S'))
    root.addHandler(handler)
    root.setLevel(loglevel)

    logging.info('VERBOSE MODE ENABLED')
    logging.debug('DEBUG MODE ENABLED')
