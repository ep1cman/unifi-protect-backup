"""Console script for unifi_protect_backup."""

import re

import click
from aiorun import run  # type: ignore
from dateutil.relativedelta import relativedelta

from unifi_protect_backup import __version__
from unifi_protect_backup.unifi_protect_backup_core import UnifiProtectBackup
from unifi_protect_backup.utils import human_readable_to_float

DETECTION_TYPES = ["motion", "person", "vehicle", "ring"]


def _parse_detection_types(ctx, param, value):
    # split columns by ',' and remove whitespace
    types = [t.strip() for t in value.split(',')]

    # validate passed columns
    for t in types:
        if t not in DETECTION_TYPES:
            raise click.BadOptionUsage("detection-types", f"`{t}` is not an available detection type.", ctx)

    return types


def parse_rclone_retention(ctx, param, retention) -> relativedelta:
    """Parses the rclone `retention` parameter into a relativedelta which can then be used to calculate datetimes."""
    matches = {k: int(v) for v, k in re.findall(r"([\d]+)(ms|s|m|h|d|w|M|y)", retention)}

    # Check that we matched the whole string
    if len(retention) != len(''.join([f"{v}{k}" for k, v in matches.items()])):
        raise click.BadParameter("See here for expected format: https://rclone.org/docs/#time-option")

    return relativedelta(
        microseconds=matches.get("ms", 0) * 1000,
        seconds=matches.get("s", 0),
        minutes=matches.get("m", 0),
        hours=matches.get("h", 0),
        days=matches.get("d", 0),
        weeks=matches.get("w", 0),
        months=matches.get("M", 0),
        years=matches.get("y", 0),
    )


@click.command(context_settings=dict(max_content_width=100))
@click.version_option(__version__)
@click.option('--address', required=True, envvar='UFP_ADDRESS', help='Address of Unifi Protect instance')
@click.option('--port', default=443, envvar='UFP_PORT', show_default=True, help='Port of Unifi Protect instance')
@click.option('--username', required=True, envvar='UFP_USERNAME', help='Username to login to Unifi Protect instance')
@click.option('--password', required=True, envvar='UFP_PASSWORD', help='Password for Unifi Protect user')
@click.option(
    '--verify-ssl/--no-verify-ssl',
    default=True,
    show_default=True,
    envvar='UFP_SSL_VERIFY',
    help="Set if you do not have a valid HTTPS Certificate for your instance",
)
@click.option(
    '--rclone-destination',
    required=True,
    envvar='RCLONE_DESTINATION',
    help="`rclone` destination path in the format {rclone remote}:{path on remote}."
    " E.g. `gdrive:/backups/unifi_protect`",
)
@click.option(
    '--retention',
    default='7d',
    show_default=True,
    envvar='RCLONE_RETENTION',
    help="How long should event clips be backed up for. Format as per the `rclone1 time option format "
    "(https://rclone.org/docs/#time-option)",
    callback=parse_rclone_retention,
)
@click.option(
    '--rclone-args',
    default='',
    envvar='RCLONE_ARGS',
    help="Optional extra arguments to pass to `rclone rcat` directly. Common usage for this would "
    "be to set a bandwidth limit, for example.",
)
@click.option(
    '--rclone-purge-args',
    default='',
    envvar='RCLONE_PURGE_ARGS',
    help="Optional extra arguments to pass to `rclone delete` directly. Common usage for this would "
    "be to execute a permanent delete instead of using the recycle bin on a destination. "
    "Google Drive example: `--drive-use-trash=false`",
)
@click.option(
    '--detection-types',
    envvar='DETECTION_TYPES',
    default=','.join(DETECTION_TYPES),
    show_default=True,
    help="A comma separated list of which types of detections to backup. "
    f"Valid options are: {', '.join([f'`{t}`' for t in DETECTION_TYPES])}",
    callback=_parse_detection_types,
)
@click.option(
    '--ignore-camera',
    'ignore_cameras',
    multiple=True,
    envvar="IGNORE_CAMERAS",
    help="IDs of cameras for which events should not be backed up. Use multiple times to ignore "
    "multiple IDs. If being set as an environment variable the IDs should be separated by whitespace.",
)
@click.option(
    '--file-structure-format',
    envvar='FILE_STRUCTURE_FORMAT',
    default="{camera_name}/{event.start:%Y-%m-%d}/{event.start:%Y-%m-%dT%H-%M-%S} {detection_type}.mp4",
    show_default=True,
    help="A Python format string used to generate the file structure/name on the rclone remote."
    "For details of the fields available, see the projects `README.md` file.",
)
@click.option(
    '-v',
    '--verbose',
    count=True,
    help="How verbose the logging output should be."
    """
    \n
    None: Only log info messages created by `unifi-protect-backup`, and all warnings

    -v: Only log info & debug messages created by `unifi-protect-backup`, and all warnings

    -vv: Log info & debug messages created by `unifi-protect-backup`, command output, and all warnings

    -vvv Log debug messages created by `unifi-protect-backup`, command output, all info messages, and all warnings

    -vvvv: Log debug messages created by `unifi-protect-backup` command output, all info messages,
all warnings, and websocket data

    -vvvvv: Log websocket data, command output, all debug messages, all info messages and all warnings
""",
)
@click.option(
    '--sqlite_path',
    default='events.sqlite',
    envvar='SQLITE_PATH',
    help="Path to the SQLite database to use/create",
)
@click.option(
    '--color-logging/--plain-logging',
    default=False,
    show_default=True,
    envvar='COLOR_LOGGING',
    help="Set if you want to use color in logging output",
)
@click.option(
    '--download-buffer-size',
    default='512MiB',
    show_default=True,
    envvar='DOWNLOAD_BUFFER_SIZE',
    help='How big the download buffer should be (you can use suffixes like "B", "KiB", "MiB", "GiB")',
    callback=lambda ctx, param, value: human_readable_to_float(value),
)
@click.option(
    '--purge_interval',
    default='1d',
    show_default=True,
    envvar='PURGE_INTERVAL',
    help="How frequently to check for file to purge.\n\nNOTE: Can create a lot of API calls, so be careful if "
    "your cloud provider charges you per api call",
    callback=parse_rclone_retention,
)
@click.option(
    '--apprise-notifier',
    'apprise_notifiers',
    multiple=True,
    envvar="APPRISE_NOTIFIERS",
    help="""\b
Apprise URL for sending notifications.
E.g: ERROR,WARNING=tgram://[BOT KEY]/[CHAT ID]

You can use this parameter multiple times to use more than one notification platform.

The following notification tags are available (corresponding to the respective logging levels):

    ERROR, WARNING, INFO, DEBUG, EXTRA_DEBUG, WEBSOCKET_DATA

If no tags are specified, it defaults to ERROR

More details about supported platforms can be found here: https://github.com/caronc/apprise""",
)
@click.option(
    '--skip-missing',
    default=False,
    show_default=True,
    is_flag=True,
    envvar='SKIP_MISSING',
    help="""\b
If set, events which are 'missing' at the start will be ignored.
Subsequent missing events will be downloaded (e.g. a missed event)
""",
)
@click.option(
    '--download-rate-limit',
    default=None,
    show_default=True,
    envvar='DOWNLOAD_RATELIMIT',
    type=float,
    help="Limit how events can be downloaded in one minute. Disabled by default",
)
@click.option(
    '--max-event-length',
    default=2 * 60 * 60,
    show_default=True,
    envvar='MAX_EVENT_LENGTH',
    type=int,
    help="Only download events shorter than this maximum length, in seconds",
)
def main(**kwargs):
    """A Python based tool for backing up Unifi Protect event clips as they occur."""
    event_listener = UnifiProtectBackup(**kwargs)
    run(event_listener.start(), stop_on_unhandled_errors=True)


if __name__ == "__main__":
    main()  # pragma: no cover
