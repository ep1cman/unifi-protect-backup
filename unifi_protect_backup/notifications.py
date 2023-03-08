"""A 'singleton' module for registering apprise notifiers."""

import apprise

notifier = apprise.Apprise()


def add_notification_service(url):
    """Add apprise URI with support for tags e.g. TAG1,TAG2=PROTOCOL://settings."""
    config = apprise.AppriseConfig()
    config.add_config(url, format='text')

    # If not tags are specified, default to errors otherwise ALL logging will
    # be spammed to the notification service
    if not config.servers()[0].tags:
        config.servers()[0].tags = {'ERROR'}

    notifier.add(config)
