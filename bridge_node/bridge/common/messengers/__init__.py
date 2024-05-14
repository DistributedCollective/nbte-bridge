import json
import logging
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger(__name__)


class Messenger(ABC):
    @abstractmethod
    def send_message(
        self,
        *,
        title: str,
        message: str,
        alert: bool = False,
    ):
        pass


class CombinedMessenger(Messenger):
    def __init__(self, messengers):
        self.messengers = messengers

    def send_message(
        self,
        *,
        title: str,
        message: str,
        alert: bool = False,
    ):
        for messenger in self.messengers:
            messenger.send_message(
                title=title,
                message=message,
                alert=alert,
            )


class NullMessenger(Messenger):
    def send_message(
        self,
        *,
        title: str,
        message: str,
        alert: bool = False,
    ):
        logger.info("NullMessenger: %s %s %s", title, message, "ALERT!" if alert else "")


class DiscordMessenger(Messenger):
    def __init__(
        self,
        webhook_url: str,
        username: str = "Sovryn BOT",
    ):
        self.webhook_url = webhook_url
        self.username = username

    def send_message(
        self,
        *,
        title: str,
        message: str,
        alert: bool = False,
    ):
        try:
            self._send_message(title=title, message=message, alert=alert)
        except Exception:
            logger.exception("DiscordMessenger: Error sending Discord message")

    def _send_message(self, *, title, message, alert=False):
        content = ""
        if alert:
            content += "# 🚨 Alert! 🚨\n"
        if title:
            content += f"## {title}\n"
        content += message
        data = {
            "username": self.username,
            "content": content,
            # "embeds": [
            #     {
            #         "title": title,
            #         "description": message,
            #     }
            # ],
        }

        response = requests.post(
            self.webhook_url,
            json=data,
        )

        if not response.ok:
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

    def send_message(
        self,
        *,
        title: str,
        message: str,
        alert: bool = False,
    ):
        try:
            self._send_message(title=title, message=message, alert=alert)
        except Exception:
            logger.exception("SlackMessenger: Error sending Slack message")

    def _send_message(self, *, title, message, alert=False):
        if alert:
            title = f"🚨 Alert! 🚨 {title}"
        data = {
            "username": self.username,
            "icon_emoji": ":fire:" if alert else ":robot_face:",
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
