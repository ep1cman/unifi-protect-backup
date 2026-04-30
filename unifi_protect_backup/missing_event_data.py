# noqa: D100

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class MissingEventData:
    """Stores data used for MissingEventChecker."""

    def __init__(self, start_time: datetime) -> None:
        """Init.

        Args:
            start_time (datetime): Time to start first missing events checker with

        """
        self.start_time: datetime = start_time

    def update_start_time(self, start_time: datetime):
        """Update the start time if it is earlier than the last start time.

        Args:
            start_time (datetime): New start time

        """
        if start_time < self.start_time:
            logger.extra_debug(  # type: ignore
                f"Making next missing events checker earlier: '{start_time.strftime('%Y-%m-%dT%H-%M-%S')}'"
            )
            self.start_time = start_time

    def get_start_time(self) -> datetime:
        """Get the start time."""
        return self.start_time

    def set_start_time(self, start_time: datetime):
        """Set the start time to a new datetime.

        Args:
            start_time (datetime): New start time

        """
        self.start_time = start_time
