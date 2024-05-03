import json
import logging
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger(__name__)


class Messenger(ABC):
    @abstractmethod
    def send_message(self, *, title, message):
        pass


class CombinedMessenger(Messenger):
    def __init__(self, messengers):
        self.messengers = messengers

    def send_message(self, *, title, message):
        for messenger in self.messengers:
            messenger.send_message(title=title, message=message)


class NullMessenger(Messenger):
    def send_message(self, *, title, message):
        logger.warning(f"NullMessenger: {title} {message}")


class DiscordMessenger(Messenger):
    def __init__(
        self,
        webhook_url: str,
        username: str = "Sovryn BOT",
    ):
        self.webhook_url = webhook_url
        self.username = username

    def send_message(self, *, title, message):
        data = {
            "username": self.username,
            "content": "Testing Discord Webhook",
            "embeds": [
                {
                    "title": title,
                    "description": message,
                }
            ],
        }

        response = requests.post(
            self.webhook_url,
            json=data,
        )

        if response.status_code != 200:
            logger.warning(
                f"Request to Discord returned an error {response.status_code}, the response is:\n{response.text}"
            )


class SlackMessenger(Messenger):
    def __init__(
        self,
        webhook_url: str,
        username: str = "Sovryn BOT",
        channel: str = "",
    ):
        self.webhook_url = webhook_url
        self.username = username
        self.channel = channel

    def send_message(self, *, title, message):
        """Minted
        notification_message: str
        attachments: list
        """
        data = {
            "username": self.username,
            "icon_emoji": ":robot_face:",
            "channel": self.channel,
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": title,
                    },
                }
            ]
            if title
            else [],
        }

        data["blocks"].append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            },
        )

        response = requests.post(
            self.webhook_url,
            data=json.dumps(data),
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            logger.warning(
                f"Request to Slack returned an error {response.status_code}, the response is:\n{response.text}"
            )
