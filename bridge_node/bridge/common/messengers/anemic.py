from anemic.ioc import Container, service

from bridge.config import Config

from . import CombinedMessenger, DiscordMessenger, Messenger, NullMessenger, SlackMessenger


@service(scope="global", interface_override=Messenger)
def messenger_factory(container: Container):
    config = container.get(interface=Config)
    btc_network = config.btc_network
    username = f"NBTEBridge [{btc_network}]"
    messengers = []
    if not config.slack_webhook_url and not config.discord_webhook_url:
        return NullMessenger()
    if config.slack_webhook_url:
        messengers.append(
            SlackMessenger(
                webhook_url=config.slack_webhook_url,
                channel=config.slack_webhook_channel,
                username=username,
            )
        )
    if config.discord_webhook_url:
        messengers.append(
            DiscordMessenger(
                webhook_url=config.discord_webhook_url,
                username=username,
            )
        )
    return CombinedMessenger(messengers)
