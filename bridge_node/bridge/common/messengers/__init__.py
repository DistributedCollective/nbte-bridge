import datetime
import json
import logging
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger(__name__)

SLACK_CHANNEL = "#sovryn-nbte-bridge-alerts"


class Messenger(ABC):
    @abstractmethod
    def send_message(self, *, title, message, msg_type):
        pass


class CombinedMessenger(Messenger):
    def __init__(self, messengers):
        self.messengers = messengers

    def send_message(self, *, title, message, msg_type):
        for messenger in self.messengers:
            messenger.send_message(title=title, message=message, msg_type=msg_type)


class NullMessenger(Messenger):
    def send_message(self, *, title, message, _):
        logger.warning(f"NullMessenger: {title} {message}")


class DiscordMessenger(Messenger):
    def __init__(
        self,
        webhook_url: str,
        username: str = "Sovryn BOT",
    ):
        self.webhook_url = webhook_url
        self.username = username

    def send_message(self, *, title, message, msg_type):
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
    ):
        self.webhook_url = webhook_url
        self.username = username

    @staticmethod
    def message_type(msg_type: str):
        color = {"danger": "#f72d2d", "good": "#0ce838", "warning": "#f2c744"}
        return color[msg_type]

    def create_attachment_template(self, title, message, msg_type):
        color_code = self.message_type(msg_type)
        now = datetime.datetime.now(tz=datetime.UTC)
        slack_report_at = "<!date^{timestamp}^{date} at {time}|{date_str}>".format(
            timestamp=int(now.timestamp()),
            date_str=now.strftime("%B %d, %Y %H:%M:%S"),
            date="{date}",
            time="{time}",
        )
        return [
            {
                "color": color_code,
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*{title}* ({slack_report_at})",
                        },
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": f"{message}"},
                    },
                ],
            }
        ]

    def send_message(self, *, title, message, msg_type):
        """Minted
        notification_message: str
        attachments: list
        """
        data = {
            "username": self.username,
            "icon_emoji": ":robot_face:",
        }
        attachments = self.create_attachment_template(title, message, msg_type)
        if not attachments:
            logger.warning("No attachments provided")

        data["channel"] = SLACK_CHANNEL
        data["attachments"] = attachments

        response = requests.post(
            self.webhook_url,
            data=json.dumps(data),
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            logger.warning(
                f"Request to Slack returned an error {response.status_code}, the response is:\n{response.text}"
            )
