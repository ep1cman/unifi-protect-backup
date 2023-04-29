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

# Setup

## Unifi Protect Account Setup
In order to connect to your unifi protect instance, you will first need to setup a local admin account:

* Login to your *Local Portal* on your UniFiOS device, and click on *Users*
* Open the `Roles` tab and click `Add Role` in the top right.
* Give the role a name like `unifi protect backup` and give it `Full Management` permissions for the unifi protect app.
* Now switch to the `User` tab and click `Add User` in the top right, and fill out the form. Specific Fields to pay attention to:
  * Role: Must be the role created in the last step
  * Account Type: *Local Access Only*
* Click *Add* in at the bottom Right.
* Select the newly created user in the list, and navigate to the `Assignments` tab in the left-hand pane, and ensure all cameras are ticked.

## Installation

*The prefered way to run this tool is using a container*

### Docker Container
You can run this tool as a container if you prefer with the following command.
Remember to change the variable to make your setup.

> **Note**
> As of version 0.8.0, the event database needs to be persisted for the tool to function properly
> please see the updated commands below

#### Backing up locally:
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

#### Backing up to cloud storage:
In order to backup to cloud storage you need to provide a `rclone.conf` file.

If you do not already have a `rclone.conf` file you can create one as follows:
```
$ docker run -it --rm -v $PWD:/root/.config/rclone --entrypoint rclone ghcr.io/ep1cman/unifi-protect-backup config
```
Follow the interactive configuration process, this will create a `rclone.conf`
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
  -v '/path/to/rclone.conf':'/config/rclone/rclone.conf' \
  -v '/path/to/save/database':/config/database/ \
  ghcr.io/ep1cman/unifi-protect-backup
```

### Installing on host:
1. Install `rclone`. Instructions for your platform can be found here: https://rclone.org/install/#quickstart
2. Configure the `rclone` remote you want to backup to. Instructions can be found here: https://rclone.org/docs/#configure
3. `pip install unifi-protect-backup`
4. Optional: Install `ffprobe` so that `unifi-protect-backup` can check the length of the clips it downloads


# Usage

```
Usage: unifi-protect-backup [OPTIONS]

  A Python based tool for backing up Unifi Protect event clips as they occur.

Options:
  --version                       Show the version and exit.
  --address TEXT                  Address of Unifi Protect instance  [required]
  --port INTEGER                  Port of Unifi Protect instance  [default: 443]
  --username TEXT                 Username to login to Unifi Protect instance  [required]
  --password TEXT                 Password for Unifi Protect user  [required]
  --verify-ssl / --no-verify-ssl  Set if you do not have a valid HTTPS Certificate for your
                                  instance  [default: verify-ssl]
  --rclone-destination TEXT       `rclone` destination path in the format {rclone remote}:{path on
                                  remote}. E.g. `gdrive:/backups/unifi_protect`  [required]
  --retention TEXT                How long should event clips be backed up for. Format as per the
                                  `--max-age` argument of `rclone`
                                  (https://rclone.org/filtering/#max-age-don-t-transfer-any-file-
                                  older-than-this)  [default: 7d]
  --rclone-args TEXT              Optional extra arguments to pass to `rclone rcat` directly.
                                  Common usage for this would be to set a bandwidth limit, for
                                  example.
  --rclone-purge-args TEXT        Optional extra arguments to pass to `rclone delete` directly.
                                  Common usage for this would be to execute a permanent delete
                                  instead of using the recycle bin on a destination.
                                  Google Drive example: `--drive-use-trash=false`
  --detection-types TEXT          A comma separated list of which types of detections to backup.
                                  Valid options are: `motion`, `person`, `vehicle`, `ring`
                                  [default: motion,person,vehicle,ring]
  --ignore-camera TEXT            IDs of cameras for which events should not be backed up. Use
                                  multiple times to ignore multiple IDs. If being set as an
                                  environment variable the IDs should be separated by whitespace.
  --file-structure-format TEXT    A Python format string used to generate the file structure/name
                                  on the rclone remote.For details of the fields available, see
                                  the projects `README.md` file.  [default: {camera_name}/{event.s
                                  tart:%Y-%m-%d}/{event.end:%Y-%m-%dT%H-%M-%S}
                                  {detection_type}.mp4]
  -v, --verbose                   How verbose the logging output should be.
                                  
                                      None: Only log info messages created by `unifi-protect-
                                      backup`, and all warnings
                                  
                                      -v: Only log info & debug messages created by `unifi-
                                      protect-backup`, and all warnings
                                  
                                      -vv: Log info & debug messages created by `unifi-protect-
                                      backup`, command output, and all warnings
                                  
                                      -vvv Log debug messages created by `unifi-protect-backup`,
                                      command output, all info messages, and all warnings
                                  
                                      -vvvv: Log debug messages created by `unifi-protect-backup`
                                      command output, all info messages, all warnings, and
                                      websocket data
                                  
                                      -vvvvv: Log websocket data, command output, all debug
                                      messages, all info messages and all warnings  [x>=0]
  --sqlite_path TEXT              Path to the SQLite database to use/create
  --color-logging / --plain-logging
                                  Set if you want to use color in logging output  [default: plain-
                                  logging]
  --download-buffer-size TEXT     How big the download buffer should be (you can use suffixes like
                                  "B", "KiB", "MiB", "GiB")  [default: 512MiB]
  --purge_interval TEXT           How frequently to check for file to purge.
                                  
                                  NOTE: Can create a lot of API calls, so be careful if your cloud
                                  provider charges you per api call  [default: 1d]
  --apprise-notifier TEXT         Apprise URL for sending notifications.
                                  E.g: ERROR,WARNING=tgram://[BOT KEY]/[CHAT ID]
                                  
                                  You can use this parameter multiple times to use more than one
                                  notification platform.
                                  
                                  The following notification tags are available (corresponding to
                                  the respective logging levels):
                                  
                                      ERROR, WARNING, INFO, DEBUG, EXTRA_DEBUG, WEBSOCKET_DATA
                                  
                                  If no tags are specified, it defaults to ERROR
                                  
                                  More details about supported platforms can be found here:
                                  https://github.com/caronc/apprise
  --skip-missing                  If set, events which are 'missing' at the start will be ignored. 
                                  Subsequent missing events will be downloaded (e.g. a missed event)  [default: False]
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
- `RCLONE_PURGE_ARGS`
- `IGNORE_CAMERAS`
- `DETECTION_TYPES`
- `FILE_STRUCTURE_FORMAT`
- `SQLITE_PATH`
- `DOWNLOAD_BUFFER_SIZE`
- `COLOR_LOGGING`
- `PURGE_INTERVAL`
- `APPRISE_NOTIFIERS`
- `SKIP_MISSING`

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

## Skipping initially missing events
If you prefer to avoid backing up the entire backlog of events, and would instead prefer to back up events that occur from 
now on, you can use the `--skip-missing` flag. This does not enable the periodic check for missing event (e.g. one that was missed by a disconnection) but instead marks all missing events at start-up as backed up.

If you use this feature it is advised that your run the tool once with this flag, then stop it once the database has been created and the events are ignored. Keeping this flag set permanently could cause events to be missed if the tool crashes and is restarted etc.

# A note about `rclone` backends and disk wear
This tool attempts to not write the downloaded files to disk to minimise disk wear, and instead streams them directly to 
rclone. Sadly, not all storage backends supported by `rclone` allow "Stream Uploads". Please refer to the `StreamUpload` column on this table to see which one do and don't: https://rclone.org/overview/#optional-features

If you are using a storage medium with poor write durability e.g. an SD card on a Raspberry Pi, it is advised to avoid
such backends. 

If you are running on a linux host you can setup `rclone` to use `tmpfs` (which is in RAM) to store its temp files, but this will significantly increase memory usage of the tool.

### Running Docker Container (LINUX ONLY)
Add the following arguments to your docker run command:
```
-e RCLONE_ARGS='--temp-dir=/rclone_tmp'
--tmpfs /rclone_tmp
```

### Running Directly (LINUX ONLY)
```
sudo mkdir /mnt/tmpfs
sudo mount -o size=1G -t tmpfs none /mnt/tmpfs
$ unifi-protect-backup --rclone-args "--temp-dir=/mnt/tmpfs"
```

To make this persist reboots add the following to `/etc/fstab`:
```
tmpfs /mnt/tmpfs tmpfs nosuid,nodev,noatime 0 0
```

# Running Backup Tool as a Service (LINUX ONLY)
You can create a service that will run the docker or local version of this backup tool. The service can be configured to launch on boot. This is likely the preferred way you want to execute the tool once you have it completely configured and tested so it is continiously running.

First create a service configuration file. You can replace `protectbackup` in the filename below with the name you wish to use for your service, if you change it remember to change the other locations in the following scripts as well.

```
sudo nano /lib/systemd/system/protectbackup.service
```

Next edit the content and fill in the 4 placeholders indicated by {}, replace these placeholders (including the leading `{` and trailing `}` characters) with the values you are using.

```
[Unit]
Description=Unifi Protect Backup

[Service]
User={your machine username}
Group={your machine user group, could be the same as the username}
Restart=on-abort
WorkingDirectory=/home/{your machine username}
ExecStart={put your complete docker or local command here}

[Install]
WantedBy=multi-user.target
```

Now enable the service and then start the service.

```
sudo systemctl enable protectbackup.service
sudo systemctl start protectbackup.service
```

To check the status of the service use this command.

```
sudo systemctl status protectbackup.service --no-pager
```

# Debugging

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

# Credits
- All the contributors who have helped make this project:
<a href="https://github.com/ep1cman/unifi-protect-backup/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=ep1cman/unifi-protect-backup" />
</a>


- Heavily utilises [`pyunifiprotect`](https://github.com/briis/pyunifiprotect) by [@briis](https://github.com/briis/)
- All the cloud functionality is provided by [`rclone`](https://rclone.org/)
- This package was created with [Cookiecutter](https://github.com/audreyr/cookiecutter) and the [waynerv/cookiecutter-pypackage](https://github.com/waynerv/cookiecutter-pypackage) project template.

# Star History

[![Star History Chart](https://api.star-history.com/svg?repos=ep1cman/unifi-protect-backup&type=Date)](https://star-history.com/#ep1cman/unifi-protect-backup&Date)
