"""Logging initializer for kcommit-analysis-pipeline.

Call setup_logging(verbose) once at the start of each stage or tool.
Colorizes output based on log level when writing to a TTY.
"""
import logging
import sys

VERBOSE = 0


def setup_logging(verbose: int = 0) -> None:
    """Initialize the root logger.

    verbose=0  → WARNING+
    verbose=1  → INFO+    (-v)
    verbose=2  → DEBUG+   (-vv)
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
        '%(asctime)s.%(msecs)03d %(levelname)s %(module)s - '
        '%(message)s'
        if verbose < 2 else
        '%(asctime)s.%(msecs)03d %(levelname)s %(module)s - '
        '(%(filename)s:%(lineno)d/%(funcName)s): %(message)s'
    )

    logging.basicConfig(
        format=fmt,
        datefmt='%Y%m%d %H:%M:%S',
        level=loglevel,
    )

    # Colorize if the root logger now has a StreamHandler to a TTY
    for handler in logging.root.handlers:
        if isinstance(handler, logging.StreamHandler) and _is_tty(handler):
            handler.setFormatter(_ColorFormatter(handler.formatter))

    logging.info('VERBOSE MODE ENABLED')
    logging.debug('DEBUG MODE ENABLED')


def _is_tty(handler: logging.StreamHandler) -> bool:
    try:
        return handler.stream.isatty()
    except Exception:
        return False


_LEVEL_COLORS = {
    logging.DEBUG:    '\033[36m',    # cyan
    logging.INFO:     '\033[32m',    # green
    logging.WARNING:  '\033[33m',    # yellow
    logging.ERROR:    '\033[31m',    # red
    logging.CRITICAL: '\033[35m',    # magenta
}
_RESET = '\033[0m'


class _ColorFormatter(logging.Formatter):
    """Wrap an existing Formatter, adding ANSI colour codes per level."""

    def __init__(self, base: logging.Formatter) -> None:
        super().__init__()
        # Copy the format string and datefmt from the existing formatter
        self._style  = base._style
        self._fmt    = base._fmt
        self.datefmt = base.datefmt

    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno, '')
        msg   = super().format(record)
        return f'{color}{msg}{_RESET}' if color else msg
