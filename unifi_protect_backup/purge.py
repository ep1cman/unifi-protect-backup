# noqa: D100

import logging
import time
from datetime import datetime

import aiosqlite
from dateutil.relativedelta import relativedelta

from unifi_protect_backup.utils import run_command, wait_until

logger = logging.getLogger(__name__)


async def delete_file(file_path, rclone_purge_args):
    """Deletes `file_path` via rclone."""
    returncode, stdout, stderr = await run_command(f'rclone delete -vv "{file_path}" {rclone_purge_args}')
    if returncode != 0:
        logger.error(f" Failed to delete file: '{file_path}'")


async def tidy_empty_dirs(base_dir_path):
    """Deletes any empty directories in `base_dir_path` via rclone."""
    returncode, stdout, stderr = await run_command(f'rclone rmdirs -vv --ignore-errors --leave-root "{base_dir_path}"')
    if returncode != 0:
        logger.error(" Failed to tidy empty dirs")


class Purge:
    """Deletes old files from rclone remotes."""

    def __init__(
        self,
        db: aiosqlite.Connection,
        retention: relativedelta,
        rclone_destination: str,
        interval: relativedelta = relativedelta(days=1),
        rclone_purge_args: str = "",
    ):
        """Init.

        Args:
            db (aiosqlite.Connection): Async SQlite database connection to purge clips from
            retention (relativedelta): How long clips should be kept
            rclone_destination (str): What rclone destination the clips are stored in
            interval (relativedelta): How often to purge old clips
            rclone_purge_args (str): Optional extra arguments to pass to `rclone delete` directly.
        """
        self._db: aiosqlite.Connection = db
        self.retention: relativedelta = retention
        self.rclone_destination: str = rclone_destination
        self.interval: relativedelta = interval
        self.rclone_purge_args: str = rclone_purge_args

    async def start(self):
        """Main loop - runs forever."""
        while True:
            try:
                deleted_a_file = False

                # For every event older than the retention time
                retention_oldest_time = time.mktime((datetime.now() - self.retention).timetuple())
                async with self._db.execute(
                    f"SELECT * FROM events WHERE end < {retention_oldest_time}"
                ) as event_cursor:
                    async for event_id, event_type, camera_id, event_start, event_end in event_cursor:

                        logger.info(f"Purging event: {event_id}.")

                        # For every backup for this event
                        async with self._db.execute(f"SELECT * FROM backups WHERE id = '{event_id}'") as backup_cursor:
                            async for _, remote, file_path in backup_cursor:
                                logger.debug(f" Deleted: {remote}:{file_path}")
                                await delete_file(f"{remote}:{file_path}", self.rclone_purge_args)
                                deleted_a_file = True

                        # delete event from database
                        # entries in the `backups` table are automatically deleted by sqlite triggers
                        await self._db.execute(f"DELETE FROM events WHERE id = '{event_id}'")
                        await self._db.commit()

                if deleted_a_file:
                    await tidy_empty_dirs(self.rclone_destination)

            except Exception as e:
                logger.error("Unexpected exception occurred during purge:", exc_info=e)

            next_purge_time = datetime.now() + self.interval
            logger.extra_debug(f'sleeping until {next_purge_time}')
            await wait_until(next_purge_time)
