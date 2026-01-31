import os
from typing import Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError


def send_email(
    to_address: str,
    subject: str,
    html_body: str,
    text_body: str,
    from_address: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> None:
    """Send an email via Amazon SES.

    Requires the following environment variables:
      - AWS_REGION (e.g., 'eu-west-1')
      - SES_FROM_EMAIL (verified identity in SES)
    Optionally:
      - SES_CONFIGURATION_SET (an existing SES configuration set name)
    """
    region = os.getenv("AWS_REGION", "eu-west-1")
    sender = from_address or os.getenv("SES_FROM_EMAIL")
    if not sender:
        raise ValueError("SES_FROM_EMAIL environment variable is required to send emails")
    configuration_set = os.getenv("SES_CONFIGURATION_SET")

    client = boto3.client("ses", region_name=region)

    message = {
        "Subject": {"Data": subject, "Charset": "UTF-8"},
        "Body": {
            "Text": {"Data": text_body or "", "Charset": "UTF-8"},
            "Html": {"Data": html_body or "", "Charset": "UTF-8"},
        },
    }

    kwargs = {
        "Source": sender,
        "Destination": {"ToAddresses": [to_address]},
        "Message": message,
    }
    if reply_to:
        kwargs["ReplyToAddresses"] = [reply_to]
    if configuration_set:
        kwargs["ConfigurationSetName"] = configuration_set

    try:
        client.send_email(**kwargs)
    except (BotoCoreError, ClientError) as exc:
        # In production you might want to log this error to an error tracker
        # We fail silently to avoid leaking details to users.
        # Re-raise if strict behavior is desired.
        print(f"SES send_email failed: {exc}")


