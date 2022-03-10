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
- Supports uploading to a [wide range of storage systems using `rclone`](https://rclone.org/overview/)
- Performs nightly pruning of old clips

## Requirements
- Python 3.9+
- Unifi Protect version 1.20 or higher (as per [`pyunifiproect`](https://github.com/briis/pyunifiprotect))
- `rclone` installed with at least one remote configured.

## Installation

1. Install `rclone`. Instructions for your platform can be found here: https://rclone.org/install/#quickstart
2. Configure the `rclone` remote you want to backup to. Instructions can be found here: https://rclone.org/docs/#configure
3. `pip install unifi-protect-backup`
4. Optional: Install `ffprobe` so that `unifi-protect-backup` can check the length of the clips it downloads

## Usage

:warning: **Potential Data Loss**: Be very careful when setting the `rclone-destination`, at midnight every day it will
delete any files older than `retention`. It is best to give `unifi-protect-backup` its own directory.

```
Usage: unifi-protect-backup [OPTIONS]

  A Python based tool for backing up Unifi Protect event clips as they occur.

Options:
  --address TEXT                  Address of Unifi Protect instance
                                  [required]
  --port INTEGER                  Port of Unifi Protect instance
  --username TEXT                 Username to login to Unifi Protect instance
                                  [required]
  --password TEXT                 Password for Unifi Protect user  [required]
  --verify-ssl / --no-verify-ssl  Set if you do not have a valid HTTPS
                                  Certificate for your instance
  --rclone-destination TEXT       `rclone` destination path in the format
                                  {rclone remote}:{path on remote}. E.g.
                                  `gdrive:/backups/unifi_protect`  [required]
  --retention TEXT                How long should event clips be backed up
                                  for. Format as per the `--max-age` argument
                                  of `rclone`
                                  (https://rclone.org/filtering/#max-age-don-
                                  t-transfer-any-file-older-than-this)
  --rclone-args TEXT              Optional arguments which are directly passed
                                  to `rclone rcat`. These can by used to set
                                  parameters such as the bandwidth limit used
                                  when pushing the files to the rclone
                                  destination, e.g., '--bwlimit=500k'. Please
                                  see the `rclone` documentation for the full
                                  set of arguments it supports
                                  (https://rclone.org/docs/). Please use
                                  responsibly.
  --ignore-camera TEXT            IDs of cameras for which events should not
                                  be backed up. Use multiple times to ignore
                                  multiple IDs. If being set as an environment
                                  variable the IDs should be separated by
                                  whitespace.
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

## Docker Container
You can run this tool as a container if you prefer with the following command.
Remember to change the variable to make your setup.


### Backing up locally
By default, if no rclone config is provided clips will be backed up to `/data`.

```
docker run \
  -e UFP_USERNAME='USERNAME' \
  -e UFP_PASSWORD='PASSWORD' \
  -e UFP_ADDRESS='UNIFI_PROTECT_IP' \
  -e UFP_SSL_VERIFY='false' \
  -v '/path/to/save/clips':'/data' \
  ghcr.io/ep1cman/unifi-protect-backup
```

### Backing up to cloud storage
In order to backup to cloud storage you need to provide a `rclone.conf` file.

If you do not already have a `rclone.conf` file you can create one as follows:
```
$ docker run -it --rm -v $PWD:/root/.config/rclone rclone/rclone config
```
Follow the interactive configuration proceed, this will create a `rclone.conf` 
file in your current directory.

Finally start the container:
```
docker run \
  -e UFP_USERNAME='USERNAME' \
  -e UFP_PASSWORD='PASSWORD' \
  -e UFP_ADDRESS='UNIFI_PROTECT_IP' \
  -e UFP_SSL_VERIFY='false' \
  -e RCLONE_DESTINATION='my_remote:/unifi_protect_backup' \
  -v '/path/to/save/clips':'/data' \
  -v `/path/to/rclone.conf':'/config/rclone.conf'
  ghcr.io/ep1cman/unifi-protect-backup
```

## Credits

- Heavily utilises [`pyunifiproect`](https://github.com/briis/pyunifiprotect) by [@briis](https://github.com/briis/)
- All the cloud functionality is provided by [`rclone`](https://rclone.org/)
- This package was created with [Cookiecutter](https://github.com/audreyr/cookiecutter) and the [waynerv/cookiecutter-pypackage](https://github.com/waynerv/cookiecutter-pypackage) project template.
