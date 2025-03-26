# noqa: D100

import logging
import time
import json
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


async def delete_old_files_by_date(base_dir_path, retention, rclone_purge_args):
    """Deletes all files older than retention period from the rclone destination.
    
    Args:
        base_dir_path (str): Base path to check for old files
        retention (relativedelta): How long files should be kept
        rclone_purge_args (str): Optional extra arguments to pass to `rclone delete` directly.
    """
    logger.info(f"Checking for any files older than retention period at {base_dir_path}")
    retention_oldest_time = time.mktime((datetime.now() - retention).timetuple())
    
    # Use rclone lsf with JSON format to get all files with their modification times
    returncode, stdout, stderr = await run_command(
        f'rclone lsf -R --format=pst --files-only -vv --json "{base_dir_path}"'
    )
    
    if returncode != 0:
        logger.error(f" Failed to list files at: '{base_dir_path}'")
        return 0
    
    deleted_count = 0
    
    # Process each line of JSON output
    for line in stdout.splitlines():
        if not line.strip():
            continue
            
        try:
            file_info = json.loads(line)
            file_path = file_info.get("Path", "")
            mod_time_str = file_info.get("ModTime", "")
            
            # Parse the modification time from rclone's format
            if mod_time_str:
                # ModTime format is RFC3339: "2006-01-02T15:04:05.000000000Z07:00"
                # Convert to timestamp for comparison
                mod_time = datetime.fromisoformat(mod_time_str.replace("Z", "+00:00"))
                mod_timestamp = time.mktime(mod_time.timetuple())
                
                # Check if file is older than retention period
                if mod_timestamp < retention_oldest_time:
                    full_path = f"{base_dir_path}/{file_path}"
                    logger.info(f"Deleting old file: {full_path}")
                    await delete_file(full_path, rclone_purge_args)
                    deleted_count += 1
            
        except json.JSONDecodeError:
            logger.error(f" Failed to parse JSON from rclone output: {line}")
        except Exception as e:
            logger.error(f" Error processing file: {e}")
    
    logger.info(f"Deleted {deleted_count} files older than retention period")
    return deleted_count


class Purge:
    """Deletes old files from rclone remotes."""

    def __init__(
        self,
        db: aiosqlite.Connection,
        retention: relativedelta,
        rclone_destination: str,
        interval: relativedelta = relativedelta(days=1),
        rclone_purge_args: str = "",
        delete_all_old_files: bool = False,
    ):
        """Init.

        Args:
            db (aiosqlite.Connection): Async SQlite database connection to purge clips from
            retention (relativedelta): How long clips should be kept
            rclone_destination (str): What rclone destination the clips are stored in
            interval (relativedelta): How often to purge old clips
            rclone_purge_args (str): Optional extra arguments to pass to `rclone delete` directly.
            delete_all_old_files (bool): Whether to delete all old files, not just those in the database.
        """
        self._db: aiosqlite.Connection = db
        self.retention: relativedelta = retention
        self.rclone_destination: str = rclone_destination
        self.interval: relativedelta = interval
        self.rclone_purge_args: str = rclone_purge_args
        self.delete_all_old_files: bool = delete_all_old_files

    async def start(self):
        """Main loop - runs forever."""
        while True:
            try:
                deleted_a_file = False

                # First, handle the database-tracked files
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
                
                # Now, if enabled, handle all old files based on modification date
                if self.delete_all_old_files:
                    files_deleted = await delete_old_files_by_date(
                        self.rclone_destination, 
                        self.retention,
                        self.rclone_purge_args
                    )
                    
                    if files_deleted > 0:
                        deleted_a_file = True

                if deleted_a_file:
                    await tidy_empty_dirs(self.rclone_destination)

            except Exception as e:
                logger.error("Unexpected exception occurred during purge:", exc_info=e)

            next_purge_time = datetime.now() + self.interval
            logger.debug(f"sleeping until {next_purge_time}")
            await wait_until(next_purge_time)
