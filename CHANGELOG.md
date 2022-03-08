# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
