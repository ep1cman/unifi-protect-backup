"""Shared test setup.

These tests exercise modules directly rather than through the CLI, so the custom log
levels ``setup_logging`` normally installs have to be registered here.
"""

import logging

from unifi_protect_backup.utils import add_logging_level

for _name, _level in (("EXTRA_DEBUG", logging.DEBUG - 1), ("WEBSOCKET_DATA", logging.DEBUG - 2)):
    if not hasattr(logging, _name):
        add_logging_level(_name, _level)
