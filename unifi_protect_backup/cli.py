"""Console script for unifi_protect_backup."""

import click


@click.command()
def main():
    """Main entrypoint."""
    click.echo("unifi-protect-backup")
    click.echo("=" * len("unifi-protect-backup"))
    click.echo("Python tool to backup unifi event clips in realtime")


if __name__ == "__main__":
    main()  # pragma: no cover
