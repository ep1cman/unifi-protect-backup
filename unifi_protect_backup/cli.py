"""Console script for unifi_protect_backup."""

import asyncio

import click

from unifi_protect_backup import UnifiProtectBackup, __version__


@click.command()
@click.version_option(__version__)
@click.option('--address', required=True, envvar='UFP_ADDRESS', help='Address of Unifi Protect instance')
@click.option('--port', default=443, envvar='UFP_PORT', help='Port of Unifi Protect instance')
@click.option('--username', required=True, envvar='UFP_USERNAME', help='Username to login to Unifi Protect instance')
@click.option('--password', required=True, envvar='UFP_PASSWORD', help='Password for Unifi Protect user')
@click.option(
    '--verify-ssl/--no-verify-ssl',
    default=True,
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
    envvar='RCLONE_RETENTION',
    help="How long should event clips be backed up for. Format as per the `--max-age` argument of "
    "`rclone` (https://rclone.org/filtering/#max-age-don-t-transfer-any-file-older-than-this)",
)
@click.option(
    '--rclone-args',
    default='',
    envvar='RCLONE_ARGS',
    help="Optional extra arguments to pass to `rclone rcat` directly. Common usage for this would "
    "be to set a bandwidth limit, for example.",
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
def main(**kwargs):
    """A Python based tool for backing up Unifi Protect event clips as they occur."""
    loop = asyncio.get_event_loop()
    event_listener = UnifiProtectBackup(**kwargs)
    loop.run_until_complete(event_listener.start())


if __name__ == "__main__":
    main()  # pragma: no cover
