import logging
import warnings
from argparse import ArgumentParser

from . import CombinedMessenger, DiscordMessenger, NullMessenger, SlackMessenger


def messenger_test_main():
    parser = ArgumentParser("Messenger tester")
    parser.add_argument("--discord-url", type=str, required=False)
    parser.add_argument("--slack-url", type=str, required=False)
    parser.add_argument("--slack-channel", type=str, required=False)
    parser.add_argument("--username", type=str, default="Tester")
    parser.add_argument("--title", type=str, default="NBTE Bridge webhook test title")
    parser.add_argument("--message", type=str, default="NBTE Bridge webhook test message")
    parser.add_argument("--alert", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, force=True)

    messengers = [
        NullMessenger(),
    ]
    if not args.discord_url and not args.slack_url:
        warnings.warn("No slack/discord url specified, defaulting to NullMessenger", stacklevel=1)
    if args.discord_url:
        messengers.append(
            DiscordMessenger(
                webhook_url=args.discord_url,
                username=args.username,
            )
        )
    if args.slack_url:
        messengers.append(
            SlackMessenger(
                webhook_url=args.slack_url,
                channel=args.slack_channel,
                username=args.username,
            )
        )
    combined_messenger = CombinedMessenger(messengers)
    combined_messenger.send_message(
        title=args.title,
        message=args.message,
        alert=args.alert,
    )


if __name__ == "__main__":
    messenger_test_main()
