# Contributing

Contributions are welcome, and they are greatly appreciated! Every little bit
helps, and credit will always be given.

You can contribute in many ways:

## Types of Contributions

### Report Bugs

Report bugs at https://github.com/ep1cman/unifi-protect-backup/issues.

If you are reporting a bug, please include:

* Your operating system name and version.
* Any details about your local setup that might be helpful in troubleshooting.
* Detailed steps to reproduce the bug.

### Fix Bugs

Look through the GitHub issues for bugs. Anything tagged with "bug" and "help
wanted" is open to whoever wants to implement it.

### Implement Features

Look through the GitHub issues for features. Anything tagged with "enhancement"
and "help wanted" is open to whoever wants to implement it.

### Write Documentation

Unifi Protect Backup could always use more documentation, whether as part of the
official Unifi Protect Backup docs, in docstrings, or even on the web in blog posts,
articles, and such.

### Submit Feedback

The best way to send feedback is to file an issue at https://github.com/ep1cman/unifi-protect-backup/issues.

If you are proposing a feature:

* Explain in detail how it would work.
* Keep the scope as narrow as possible, to make it easier to implement.
* Remember that this is a volunteer-driven project, and that contributions
  are welcome :)

## Get Started!

Ready to contribute? Here's how to set up `unifi-protect-backup` for local development.

1. Fork the `unifi-protect-backup` repo on GitHub.
2. Clone your fork locally

    ```
    $ git clone git@github.com:your_name_here/unifi-protect-backup.git
    ```

3. Ensure [poetry](https://python-poetry.org/docs/) is installed.
4. Install dependencies and start your virtualenv:

    ```
    $ poetry install -E test -E dev
    $ poetry shell
    ```

5. Create a branch for local development:

    ```
    $ git checkout -b name-of-your-bugfix-or-feature
    ```

    Now you can make your changes locally.

6. To run `unifi-protect-backup` while developing you will need to either
   be inside the `poetry shell` virtualenv or run it via poetry:

   ```
   $ poetry run unifi-protect-backup {args}
   ```

7. When you're done making changes, check that your changes pass the
   tests, including testing other Python versions, with tox:

    ```
    $ poetry run tox
    ```

8. Commit your changes and push your branch to GitHub:

    ```
    $ git add .
    $ git commit -m "Your detailed description of your changes."
    $ git push origin name-of-your-bugfix-or-feature
    ```

9. Submit a pull request through the GitHub website.

## Pull Request Guidelines

Before you submit a pull request, check that it meets these guidelines:

1. The pull request should include tests.
2. If the pull request adds functionality, the docs should be updated. Put
   your new functionality into a function with a docstring. If adding a CLI
   option, you should update the "usage" in README.md.
3. The pull request should work for Python 3.10. Check
   https://github.com/ep1cman/unifi-protect-backup/actions
   and make sure that the tests pass for all supported Python versions.

## Tips

```
$ poetry run pytest tests/test_unifi_protect_backup.py
```

To run a subset of tests.


## Deploying

A reminder for the maintainers on how to deploy.
Make sure all your changes are committed (including an entry in CHANGELOG.md).
Then run:

```
$ poetry run bump2version patch # possible: major / minor / patch
$ git push
$ git push --tags
```

GitHub Actions will then deploy to PyPI, produce a GitHub release, and a container
build if tests pass.
