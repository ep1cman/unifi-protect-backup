# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.10.5] - 2024-01-26
### Fixed
- Bumped `pyunifiprotect` version to fix issue with old version of yarl

## [0.10.4] - 2024-01-26
### Fixed
- Bumped `pyunifiprotect` version to fix issue caused by new video modes

## [0.10.3] - 2023-12-07
### Fixed
- Bumped `pyunifiprotect` version to fix issue caused by unifi protect returning invalid UUIDs

## [0.10.2] - 2023-11-21
### Fixed
- Issue where duplicate events were being downloaded causing database errors
- Default file path format now uses event start time instead of event end time which makes more logical sense

## [0.10.1] - 2023-11-01
### Fixed
- Event type enum conversion string was no longer converting to the enum value, this is now done explicitly.

## [0.10.0] - 2023-11-01
### Added
- Command line option to skip events longer than a given length (default 2 hours)
- Docker image is now based on alpine edge giving access to the latest version of rclone
### Fixed
- Failed uploads no longer write to the database, meaning they will be retried
- Fixed issue with chunked event fetch during initial ignore of events
- Fixed error when no events were fetched for the retention period

## [0.9.5] - 2023-10-07
### Fixed
- Errors caused by latest unifi protect version by bumping the version of pyunifiprotect used
- Queries for events are now chunked into groups of 500 which should help stop this tool crashing large
  unifi protect instances.

## [0.9.4] - 2023-07-29
### Fixed
- Time period parsing, 'Y' -> 'y'

## [0.9.3] - 2023-07-08
### Fixed
- Queued up downloads etc now wait for dropped connections to be re-established.

## [0.9.2] - 2023-04-21
### Fixed
- Missing event checker ignoring the "ignored cameras" list

## [0.9.1] - 2023-04-21
### Added
- Added optional argument string to pass directly to the `rclone delete` command used to purge video files

### Fixed
- Fixed download errors not counting as failures

## [0.9.0] - 2023-03-24
### Added
- The ability to send logging out via apprise notifications
- Color logging is now optional
- Events are now permanently ignored if they fail to download 10 times

## [0.8.8] - 2022-12-30
### Added
- Added ability to configure purge interval

### Fixed
- Purge interval returned to previous default of once a day

## [0.8.7] - 2022-12-11
### Fixed
- Fix improper unpacking of upload events

## [0.8.6] - 2022-12-10
### Fixed
- check that current event is not none before trying to get it it’s ID
- downloader/uploaded clear their current event once it’s been processed

## [0.8.5] - 2022-12-09
### Fixed
- use event ID of currently up/downloading event, not whole event object when checking missing events

## [0.8.4] - 2022-12-09
### Added
- Logging of remaining upload queue size

### Fixed
- Uploading files were not accounted for when checking for missing events
- Buffer size parameter is logged in human-readable format 

## [0.8.3] - 2022-12-08
### Added
- Now logs time zone settings for both the host and NVR
- Color logging is now optional and defaults to disabled (to match previous behavior before v0.8.0)
- Ability to configure download buffer size (bumped default up to 512MiB)
- Event IDs to upload/download logging

### Fixed
- Log spam when lots of events are missing, this will now only occur if the logging level is set to `EXTRA_DEBUG` (-vv)
- corrected logging not showing smart detection types
- The application no longer stalls when a video is downloaded larger than the available buffer size
- Ability to set the least verbose logging for the docker container

## [0.8.2] - 2022-12-05
### Fixed
- Fixed issue where command output was being returned with added indentation intended for logging only
- Fixed issue where some command logging was not indented
- Fixed issue where the tool could crash when run in a container if /config/database didn't exist

## [0.8.1] - 2022-12-04
version 0.8.0 was used by accident previously and PyPI would not accept it so bumping by one patch version

## [0.8.0] - 2022-12-03
Major internal refactoring. Each task is now its own class and asyncio task.

### Added
- A database of backed up events and where they are stored
- A periodic check for missed events
  - This will also ensure past events before the tool was used are backed up, up until the retention period

### Fixed
- Pruning is no longer done based on file timestamps, the database is used instead. The tool will no longer delete files it didn't create.
- Pruning now runs much more frequently (every minute) so retention periods of less than a day are now possible.


## [0.7.4] - 2022-08-21
No functional changes in this version. This is just to trigger the release CI.
### Added
- Arm docker container
- rclone debugging instructions when using docker

### Fixed
- Documentation error in rclone config path of docker container.

## [0.7.3] - 2022-07-31
### Fixed
- Updated to the 4.0.0 version of pyunifiprotect
- Added rust to the container, and bumped it to alpine 3.16

## [0.7.2] - 2022-07-17
### Fixed
- Updated to the latest version of pyunifiprotect to fix issues introduced in unifi protect 2.1.1

## [0.7.1] - 2022-06-08
### Fixed
- Updated to the latest version of pyunifiprotect to fix issues introduced in unifi protect 2.0.1
- Updated documentation to include how to set up local user accounts on unifi protect

## [0.7.0] - 2022-03-26
### Added
- Added a the ability to change the way the clip files are structured via a template string.
### Fixed
- Fixed issue where event types without clips would attempt (and fail1) to download clips
- Drastically reduced the size of the docker container
- Fixed typos in the documentation
- Some dev dependencies are now not installed as default

## [0.6.0] - 2022-03-18
### Added
- Support for doorbell ring events
- `detection_types` parameter to limit which kinds of events are backed up
### Fixed
- Actually fixed timestamps this time.

## [0.5.3] - 2022-03-11
### Fixed
- Timestamps in filenames and logging now show time in the timezone of the NVR not UTC

## [0.5.2] - 2022-03-10
### Fixed
- rclone delete command now works as expected on windows when spaces are in the file path
- Dockerfile now allows setting of user and group to run as, as well as a default config

## [0.5.1] - 2022-03-07
### Fixed
- rclone command now works as expected on windows when spaces are in the file path

## [0.5.0] - 2022-03-06
### Added
- If `ffprobe` is available, the downloaded clips length is checked and logged
### Fixed
- A time delay has been added before downloading clips to try to resolve an issue where
  downloaded clips were too short

## [0.4.0] - 2022-03-05
### Added
- A `--version` command line option to show the tools version
### Fixed
- Websocket checks are no longer logged in verbosity level 1 to reduce log spam

## [0.3.1] - 2022-02-24
### Fixed
- Now checks if the websocket connection is alive, and attempts to reconnect if it isn't.

## [0.3.0] - 2022-02-22
### Added
- New CLI argument for passing CLI arguments directly to `rclone`.

### Fixed
- A new camera getting added while running no longer crashes the application.
- A timeout during download now correctly retries the download instead of
  abandoning the event.

## [0.2.1] - 2022-02-21
### Fixed
- Retry logging formatting

## [0.2.0] - 2022-02-21
### Added
- Ability to ignore cameras
- Retry failed download/uploads
- More logging
- CI to build `dev` container
- More documentation

### Fixed
- Upload exceptions getting passed silently
- Camera ID -> Name map is no longer only looked up once at the start

## [0.1.1] - 2022-02-20
### Added
- Docker container
- Dependabot
### Changed
- Better project description
### Fixed
- Typos in docs

## [0.1.0] - 2022-02-19
### Added
- First release
