"""Shared test setup.

The package logs at custom levels (``extra_debug``, ``websocket_data``) that
``setup_logging`` installs at startup. These tests exercise modules directly rather than
going through the CLI, so the levels have to be registered here or any logging call
raises AttributeError.
"""

import logging

from unifi_protect_backup.utils import add_logging_level

for _name, _level in (("EXTRA_DEBUG", logging.DEBUG - 1), ("WEBSOCKET_DATA", logging.DEBUG - 2)):
    if not hasattr(logging, _name):
        add_logging_level(_name, _level)
