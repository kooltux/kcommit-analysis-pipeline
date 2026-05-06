"""Logging initializer for kcommit-analysis-pipeline.

Call setup_logging(verbose) once at the start of each stage.
Colorized output is emitted when stderr is a TTY (or FORCE_COLOR is set).
Color is suppressed when stderr is redirected to a file or pipe,
or when the NO_COLOR environment variable is set.
"""
import logging
import os
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


def _use_color() -> bool:
    """Return True when ANSI color should be emitted on stderr."""
    if os.environ.get('NO_COLOR'):
        return False
    if os.environ.get('FORCE_COLOR'):
        return True
    return hasattr(sys.stderr, 'isatty') and sys.stderr.isatty()


class _ColorFormatter(logging.Formatter):
    """Formatter that prepends an ANSI colour code based on log level."""

    def __init__(self, fmt=None, datefmt=None, use_color=True):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        if not self._use_color:
            return msg
        color = _LEVEL_COLORS.get(record.levelno, '')
        return f'{color}{msg}{_RESET}' if color else msg


def setup_logging(verbose: int = 0) -> None:
    """Initialize the root logger.

    verbose=0  → WARNING+   (default)
    verbose=1  → INFO+      (-v)
    verbose=2  → DEBUG+     (-vv)

    Color is applied when stderr is a TTY, NO_COLOR is unset,
    or FORCE_COLOR is set.
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
    handler.setFormatter(_ColorFormatter(fmt, datefmt='%Y%m%d %H:%M:%S',
                                         use_color=_use_color()))
    root.addHandler(handler)
    root.setLevel(loglevel)

    logging.info('VERBOSE MODE ENABLED')
    logging.debug('DEBUG MODE ENABLED')
