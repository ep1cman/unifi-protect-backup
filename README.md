# Unifi Protect Backup


[![pypi](https://img.shields.io/pypi/v/unifi-protect-backup.svg)](https://pypi.org/project/unifi-protect-backup/)
[![python](https://img.shields.io/pypi/pyversions/unifi-protect-backup.svg)](https://pypi.org/project/unifi-protect-backup/)
[![Build Status](https://github.com/ep1cman/unifi-protect-backup/actions/workflows/dev.yml/badge.svg)](https://github.com/ep1cman/unifi-protect-backup/actions/workflows/dev.yml)
[![codecov](https://codecov.io/gh/ep1cman/unifi-protect-backup/branch/main/graphs/badge.svg)](https://codecov.io/github/ep1cman/unifi-protect-backup)

A Python based tool for backing up UniFi Protect event clips as they occur.

The idea for this project came after realising that if something were to happen, e.g. a fire, or a burglary
that meant I could no longer access my UDM, all the footage recorded by all my nice expensive UniFi cameras
would have been rather pointless. With this tool, all motion and smart detection clips are immediately
backed up to off-site storage thanks to [`rclone`](https://rclone.org/), and kept for the configured
retention period.

* GitHub: <https://github.com/ep1cman/unifi-protect-backup>
* PyPI: <https://pypi.org/project/unifi-protect-backup/>
* Free software: MIT

[![Buy me a coffee](https://www.buymeacoffee.com/assets/img/custom_images/black_img.png)](https://www.buymeacoffee.com/ep1cman)

## Features

- Listens to events in real-time via the Unifi Protect websocket API
- Ensures any previous and/or missed events within the retention period are also backed up
- Supports uploading to a [wide range of storage systems using `rclone`](https://rclone.org/overview/)
- Automatic pruning of old clips

## Requirements
- Python 3.9+
- Unifi Protect version 1.20 or higher (as per [`pyunifiprotect`](https://github.com/briis/pyunifiprotect))
- `rclone` installed with at least one remote configured.

## Installation

1. Install `rclone`. Instructions for your platform can be found here: https://rclone.org/install/#quickstart
2. Configure the `rclone` remote you want to backup to. Instructions can be found here: https://rclone.org/docs/#configure
3. `pip install unifi-protect-backup`
4. Optional: Install `ffprobe` so that `unifi-protect-backup` can check the length of the clips it downloads


### Account Setup
In order to connect to your unifi protect instance, you will first need to setup a local admin account:

* Login to your *Local Portal* on your UniFiOS device, and click on *Users*
* Open the `Roles` tab and click `Add Role` in the top right.
* Give the role a name like `unifi protect backup` and give it `Full Management` permissions for the unifi protect app.
* Now switch to the `User` tab and click `Add User` in the top right, and fill out the form. Specific Fields to pay attention to:
  * Role: Must be the role created in the last step
  * Account Type: *Local Access Only*
* Click *Add* in at the bottom Right.
* Select the newly created user in the list, and navigate to the `Assignments` tab in the left-hand pane, and ensure all cameras are ticked.


## Usage

```
Usage: unifi-protect-backup [OPTIONS]

  A Python based tool for backing up Unifi Protect event clips as they occur.

Options:
  --version                       Show the version and exit.
  --address TEXT                  Address of Unifi Protect instance
                                  [required]
  --port INTEGER                  Port of Unifi Protect instance  [default:
                                  443]
  --username TEXT                 Username to login to Unifi Protect instance
                                  [required]
  --password TEXT                 Password for Unifi Protect user  [required]
  --verify-ssl / --no-verify-ssl  Set if you do not have a valid HTTPS
                                  Certificate for your instance  [default:
                                  verify-ssl]
  --rclone-destination TEXT       `rclone` destination path in the format
                                  {rclone remote}:{path on remote}. E.g.
                                  `gdrive:/backups/unifi_protect`  [required]
  --retention TEXT                How long should event clips be backed up
                                  for. Format as per the `--max-age` argument
                                  of `rclone`
                                  (https://rclone.org/filtering/#max-age-don-
                                  t-transfer-any-file-older-than-this)
                                  [default: 7d]
  --rclone-args TEXT              Optional extra arguments to pass to `rclone
                                  rcat` directly. Common usage for this would
                                  be to set a bandwidth limit, for example.
  --detection-types TEXT          A comma separated list of which types of
                                  detections to backup. Valid options are:
                                  `motion`, `person`, `vehicle`, `ring`
                                  [default: motion,person,vehicle,ring]
  --ignore-camera TEXT            IDs of cameras for which events should not
                                  be backed up. Use multiple times to ignore
                                  multiple IDs. If being set as an environment
                                  variable the IDs should be separated by
                                  whitespace.
  --file-structure-format TEXT    A Python format string used to generate the
                                  file structure/name on the rclone remote.For
                                  details of the fields available, see the
                                  projects `README.md` file.  [default: {camer
                                  a_name}/{event.start:%Y-%m-%d}/{event.end:%Y
                                  -%m-%dT%H-%M-%S} {detection_type}.mp4]
  -v, --verbose                   How verbose the logging output should be.
                                  
                                      None: Only log info messages created by
                                      `unifi-protect-backup`, and all warnings
                                  
                                      -v: Only log info & debug messages
                                      created by `unifi-protect-backup`, and
                                      all warnings
                                  
                                      -vv: Log info & debug messages created
                                      by `unifi-protect-backup`, command
                                      output, and all warnings
                                  
                                      -vvv Log debug messages created by
                                      `unifi-protect-backup`, command output,
                                      all info messages, and all warnings
                                  
                                      -vvvv: Log debug messages created by
                                      `unifi-protect-backup` command output,
                                      all info messages, all warnings, and
                                      websocket data
                                  
                                      -vvvvv: Log websocket data, command
                                      output, all debug messages, all info
                                      messages and all warnings  [x>=0]
  --sqlite_path TEXT              Path to the SQLite database to use/create
  --color-logging / --plain-logging
                                  Set if you want to use color in logging
                                  output  [default: plain-logging]
  --download-buffer-size TEXT     How big the download buffer should be (you
                                  can use suffixes like "B", "KiB", "MiB",
                                  "GiB")  [default: 512MiB]
  --purge_interval TEXT           How frequently to check for file to purge.
                                  
                                  NOTE: Can create a lot of API calls, so be
                                  careful if your cloud provider charges you per
                                  api call  [default: 1d]
  --help                          Show this message and exit.
```

The following environment variables can also be used instead of command line arguments (note, CLI arguments
always take priority over environment variables):
- `UFP_USERNAME`
- `UFP_PASSWORD`
- `UFP_ADDRESS`
- `UFP_PORT`
- `UFP_SSL_VERIFY`
- `RCLONE_RETENTION`
- `RCLONE_DESTINATION`
- `RCLONE_ARGS`
- `IGNORE_CAMERAS`
- `DETECTION_TYPES`
- `FILE_STRUCTURE_FORMAT`
- `SQLITE_PATH`
- `DOWNLOAD_BUFFER_SIZE`
- `COLOR_LOGGING`
- `PURGE_INTERVAL`

## File path formatting

By default, the application will save clips in the following structure on the provided rclone remote:
```
{camera_name}/{event.start:%Y-%m-%d}/{event.end:%Y-%m-%dT%H-%M-%S} {detection_type}.mp4
```
If you wish for the clips to be structured differently you can do this using the `--file-structure-format`
option. It uses standard [python format string syntax](https://docs.python.org/3/library/string.html#formatstrings).

The following fields are provided to the format string:
  - *event:* The `Event` object as per https://github.com/briis/pyunifiprotect/blob/master/pyunifiprotect/data/nvr.py
  - *duration_seconds:* The duration of the event in seconds
  - *detection_type:* A nicely formatted list of the event detection type and the smart detection types (if any)
  - *camera_name:* The name of the camera that generated this event

You can optionally format the `event.start`/`event.end` timestamps as per the [`strftime` format](https://docs.python.org/3/library/datetime.html#strftime-strptime-behavior) by appending it after a `:` e.g to get just the date without the time: `{event.start:%Y-%m-%d}`


## Docker Container
You can run this tool as a container if you prefer with the following command.
Remember to change the variable to make your setup.

> **Note**
> As of version 0.8.0, the event database needs to be persisted for the tool to function properly
> please see the updated commands below

### Backing up locally
By default, if no rclone config is provided clips will be backed up to `/data`.

```
docker run \
  -e UFP_USERNAME='USERNAME' \
  -e UFP_PASSWORD='PASSWORD' \
  -e UFP_ADDRESS='UNIFI_PROTECT_IP' \
  -e UFP_SSL_VERIFY='false' \
  -v '/path/to/save/clips':'/data' \
  -v '/path/to/save/database':/config/database/ \
  ghcr.io/ep1cman/unifi-protect-backup
```

### Backing up to cloud storage
In order to backup to cloud storage you need to provide a `rclone.conf` file.

If you do not already have a `rclone.conf` file you can create one as follows:
```
$ docker run -it --rm -v $PWD:/root/.config/rclone --entrypoint rclone ghcr.io/ep1cman/unifi-protect-backup config
```
Follow the interactive configuration proceed, this will create a `rclone.conf`
file in your current directory.

Finally, start the container:
```
docker run \
  -e UFP_USERNAME='USERNAME' \
  -e UFP_PASSWORD='PASSWORD' \
  -e UFP_ADDRESS='UNIFI_PROTECT_IP' \
  -e UFP_SSL_VERIFY='false' \
  -e RCLONE_DESTINATION='my_remote:/unifi_protect_backup' \
  -v '/path/to/save/clips':'/data' \
  -v `/path/to/rclone.conf':'/config/rclone/rclone.conf' \
  -v '/path/to/save/database':/config/database/ \
  ghcr.io/ep1cman/unifi-protect-backup
```

### Debugging

If you need to debug your rclone setup, you can invoke rclone directly like so:

```
docker run \
    --rm \
    -v /path/to/rclone.conf:/config/rclone/rclone.conf \
    -e RCLONE_CONFIG='/config/rclone/rclone.conf' \
    --entrypoint rclone \
    ghcr.io/ep1cman/unifi-protect-backup \
    {rclone subcommand as per: https://rclone.org/docs/#subcommands}
```

For example to check that your config file is being read properly and list the configured remotes:
```
docker run \
    --rm \
    -v /path/to/rclone.conf:/config/rclone/rclone.conf \
    -e RCLONE_CONFIG='/config/rclone/rclone.conf' \
    --entrypoint rclone \
    ghcr.io/ep1cman/unifi-protect-backup \
    listremotes
```

## Credits

- Heavily utilises [`pyunifiprotect`](https://github.com/briis/pyunifiprotect) by [@briis](https://github.com/briis/)
- All the cloud functionality is provided by [`rclone`](https://rclone.org/)
- This package was created with [Cookiecutter](https://github.com/audreyr/cookiecutter) and the [waynerv/cookiecutter-pypackage](https://github.com/waynerv/cookiecutter-pypackage) project template.
