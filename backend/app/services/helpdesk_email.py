"""Help-desk email fallback: draft generation + SMTP sending.

When the RAG pipeline cannot find reliable information the assistant offers to
email the university help desk. This module:

1. Generates a professional, deterministic email draft from the student's
   actual question (no hard-coded questions, no LLM round-trip needed).
2. Sends the draft via SMTP to the configured ``HELPDESK_EMAIL``.

Security: SMTP credentials are read from environment variables, never leave
the backend, and are never returned to the client or logged. The recipient is
always the server-configured ``HELPDESK_EMAIL`` — clients cannot change it.
User-controlled text is sanitized (control chars removed) so a question can
never inject extra message headers.
"""
import logging
import re
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)

# Canonical "I don't know" answer used by /api/ask when nothing was retrieved.
NO_INFO_ANSWER = (
    "I couldn't find reliable information about this in my available "
    "university resources."
)

_MAX_SUBJECT = 100
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RE = re.compile(r"\s+")

_INTERROGATIVE_PREFIXES = (
    "can you tell me",
    "could you tell me",
    "please tell me",
    "how do i",
    "how can i",
    "how do you",
    "how can you",
    "what is",
    "what are",
    "what was",
    "what were",
    "when is",
    "when are",
    "when was",
    "where is",
    "where are",
    "why is",
    "why are",
    "why does",
    "why do",
    "how is",
    "how are",
    "how to",
    "how do",
    "tell me",
    "what's",
    "whats",
    "can you",
    "could you",
    "please",
)

_DAYS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "mon", "tue", "wed", "thu", "fri", "sat", "sun",
}
_MONTHS = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "jan", "feb", "mar",
    "apr", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
}
_TIME_WORD = _DAYS | _MONTHS

_SMALL_WORDS = {
    "a", "an", "the", "and", "for", "on", "of", "to", "with", "in", "at",
    "by", "is", "are", "was", "were",
}


class HelpDeskEmailError(RuntimeError):
    """Raised when an email cannot be generated or sent."""


# --------------------------------------------------------------------------
# Sanitization
# --------------------------------------------------------------------------

def _sanitize(value: str) -> str:
    """Collapse whitespace and drop control chars (prevents header injection)."""
    value = _WS_RE.sub(" ", value or "")
    value = _CONTROL_RE.sub("", value)
    return value.strip()


def _strip_question_prefix(question: str) -> str:
    """Drop a leading interrogative/request prefix, e.g. 'What is'."""
    q = _sanitize(question).rstrip("?.! ")
    lower = q.lower()
    for prefix in sorted(_INTERROGATIVE_PREFIXES, key=len, reverse=True):
        if lower.startswith(prefix):
            rest = q[len(prefix):].strip()
            if rest:
                return rest
    return q


def _split_trailing_time(phrase: str) -> tuple[str, str | None]:
    """Return (core, day) when phrase ends with 'for|on <day/month>'."""
    words = phrase.split()
    if (
        len(words) >= 3
        and words[-2].lower() in ("for", "on")
        and words[-1].lower() in _TIME_WORD
    ):
        return " ".join(words[:-2]), words[-1]
    return phrase, None


def _subject_focus(phrase: str) -> str:
    """Headline-style subject noun phrase: 'Thursday Dinner Menu'."""
    words = phrase.split()
    while words and words[0].lower() in {"the", "a", "an"}:
        words = words[1:]
    core, day = _split_trailing_time(" ".join(words))
    if day:
        words = [day] + core.split()
    title = []
    for i, word in enumerate(words):
        if i > 0 and word.lower() in _SMALL_WORDS:
            title.append(word.lower())
        else:
            title.append(word.capitalize())
    return " ".join(title)


# --------------------------------------------------------------------------
# Draft generation
# --------------------------------------------------------------------------

def generate_email_draft(question: str) -> dict:
    """Build a professional email draft from the student's question.

    Returns ``{"to", "subject", "body"}``. Raises ``ValueError`` for an empty
    question and ``HelpDeskEmailError`` when no recipient is configured.
    """
    raw = _sanitize(question)
    if not raw:
        raise ValueError("Question cannot be empty")

    recipient = settings.HELPDESK_EMAIL
    if not recipient:
        raise HelpDeskEmailError(
            "HELPDESK_EMAIL is not configured on the server."
        )

    phrase = _strip_question_prefix(raw)

    if phrase:
        focus = _subject_focus(phrase)
        request = f"I would like to know {phrase}."
        provide_core, _ = _split_trailing_time(
            re.sub(r"^(?:the|a|an)\s+", "", phrase, flags=re.I)
        )
        provide = (
            f"Could you please provide the current {provide_core}?"
            if provide_core
            else "Could you please provide the relevant information?"
        )
    else:
        focus = ""
        request = f"I would like to know: {raw}"
        provide = "Could you please provide the relevant information?"

    subject = "Request for " + (focus or _sanitize(raw))
    subject = subject[: _MAX_SUBJECT].rstrip()

    body = (
        "Dear Help Desk,\n\n"
        f"{request}\n"
        f"\n{provide}\n"
        "\nThank you.\n"
        "\nRegards,\n"
        f"{settings.EMAIL_SIGNATURE_NAME}"
    )

    logger.info("Email draft generated")
    return {"to": recipient, "subject": subject, "body": body}


# --------------------------------------------------------------------------
# SMTP transport
# --------------------------------------------------------------------------

def email_configured() -> bool:
    return settings.helpdesk_configured


def send_email(
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
) -> dict:
    """Send an email to the configured help-desk recipient over SMTP.

    The ``to`` argument is accepted for the caller's convenience but any value
    is ignored in favor of the server-configured ``HELPDESK_EMAIL`` so clients
    can never redirect mail to an arbitrary SMTP destination. Raises
    ``HelpDeskEmailError`` with a safe, credential-free message on failure.
    """
    if not email_configured():
        raise HelpDeskEmailError(
            "Email service is not configured on the server."
        )

    recipient = settings.HELPDESK_EMAIL
    clean_subject = _sanitize(subject or "")
    if not clean_subject:
        clean_subject = "Request for Information"
    clean_body = (body or "").strip()
    if not clean_body:
        raise HelpDeskEmailError("Email body cannot be empty.")

    logger.info("Email send requested to %s", recipient)

    message = EmailMessage()
    message["From"] = settings.SMTP_USERNAME
    message["To"] = recipient
    message["Subject"] = clean_subject
    message.set_content(clean_body)

    try:
        if settings.SMTP_USE_TLS:
            # STARTTLS on port 587.
            server: smtplib.SMTP | smtplib.SMTP_SSL = smtplib.SMTP(
                settings.SMTP_HOST,
                int(settings.SMTP_PORT),
                timeout=settings.EMAIL_SEND_TIMEOUT,
            )
        else:
            # Implicit TLS (e.g. port 465) — wrap the connection from the start.
            server = smtplib.SMTP_SSL(
                settings.SMTP_HOST,
                int(settings.SMTP_PORT),
                timeout=settings.EMAIL_SEND_TIMEOUT,
            )
        with server:
            if settings.SMTP_USE_TLS:
                server.ehlo()
                server.starttls()
                server.ehlo()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(message)
    except HelpDeskEmailError:
        raise
    except Exception as exc:
        # Log only the exception class — SMTP auth error text can echo the
        # credentials that were sent, so the full message is never logged.
        logger.error(
            "Email send failed for %s: %s", recipient, type(exc).__name__
        )
        raise HelpDeskEmailError(
            "Unable to send the email. Please try again later."
        ) from exc

    logger.info("Email sent successfully to %s", recipient)
    return {"success": True, "message": "Email sent successfully."}