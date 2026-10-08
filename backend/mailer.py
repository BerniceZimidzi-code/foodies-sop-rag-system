import os
import smtplib
from email.message import EmailMessage
from urllib.parse import urlsplit


class EmailConfigurationError(RuntimeError):
    pass


class EmailDeliveryError(RuntimeError):
    pass


def is_email_configured() -> bool:
    username = os.getenv("FOODIES_SMTP_USERNAME", "")
    password = os.getenv("FOODIES_SMTP_PASSWORD", "")
    security = os.getenv("FOODIES_SMTP_SECURITY", "starttls").strip().casefold()
    try:
        port = int(os.getenv("FOODIES_SMTP_PORT", "587"))
    except ValueError:
        return False
    base_url = urlsplit(
        os.getenv("FOODIES_BASE_URL", "http://127.0.0.1:8127").rstrip("/")
    )
    sender = os.getenv("FOODIES_EMAIL_FROM", "").strip()
    return bool(
        os.getenv("FOODIES_SMTP_HOST", "").strip()
        and sender
        and "\r" not in sender
        and "\n" not in sender
        and bool(username) == bool(password)
        and security in {"starttls", "ssl", "none"}
        and 1 <= port <= 65535
        and base_url.scheme in {"https", "http"}
        and bool(base_url.netloc)
        and base_url.username is None
        and base_url.password is None
        and not base_url.query
        and not base_url.fragment
        and (
            base_url.scheme == "https"
            or base_url.hostname in {"localhost", "127.0.0.1", "::1"}
        )
    )


def activation_url(token: str) -> str:
    base_url = os.getenv("FOODIES_BASE_URL", "http://127.0.0.1:8127").rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (
            parsed.scheme != "https"
            and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        )
    ):
        raise EmailConfigurationError(
            "FOODIES_BASE_URL must use HTTPS, except for localhost development."
        )
    return f"{base_url}/activate#token={token}"


def send_activation_email(
    *,
    email: str,
    name: str,
    temporary_password: str,
    link: str,
) -> None:
    host = os.getenv("FOODIES_SMTP_HOST", "").strip()
    sender = os.getenv("FOODIES_EMAIL_FROM", "").strip()
    if not host or not sender:
        raise EmailConfigurationError(
            "Email is not configured. Set FOODIES_SMTP_HOST and FOODIES_EMAIL_FROM."
        )

    username = os.getenv("FOODIES_SMTP_USERNAME", "")
    password = os.getenv("FOODIES_SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise EmailConfigurationError(
            "Set both FOODIES_SMTP_USERNAME and FOODIES_SMTP_PASSWORD, or neither."
        )
    security = os.getenv("FOODIES_SMTP_SECURITY", "starttls").strip().casefold()
    if security not in {"starttls", "ssl", "none"}:
        raise EmailConfigurationError(
            "FOODIES_SMTP_SECURITY must be starttls, ssl, or none."
        )
    try:
        port = int(os.getenv("FOODIES_SMTP_PORT", "587"))
    except ValueError as exc:
        raise EmailConfigurationError("FOODIES_SMTP_PORT must be a valid port number.") from exc
    if not 1 <= port <= 65535:
        raise EmailConfigurationError("FOODIES_SMTP_PORT must be between 1 and 65535.")

    message = EmailMessage()
    message["Subject"] = "Activate your Foodies SOP Assistant account"
    message["From"] = sender
    message["To"] = email
    message.set_content(
        f"""Hello {name},

An administrator created your Foodies SOP Assistant account.

Activate your account and choose a new password using this one-time link:
{link}

Temporary password: {temporary_password}

The link expires in 24 hours. Enter the temporary password on the activation
page, then choose a new password. The link and temporary password cannot be
used again after activation.

If you were not expecting this message, contact your Foodies administrator.
"""
    )

    try:
        if security == "ssl":
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                if username:
                    server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                server.ehlo()
                if security == "starttls":
                    server.starttls()
                    server.ehlo()
                if username:
                    server.login(username, password)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailDeliveryError(
            "The invitation email could not be sent. Check SMTP settings and try again."
        ) from exc
