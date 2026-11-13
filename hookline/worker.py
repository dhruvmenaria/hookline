from datetime import datetime, timedelta, timezone

from .config import settings
from .models import DeliveryAttempt, Event


def retry_delay(attempt_number: int) -> int:
    return min(settings.retry_base_seconds * (2 ** max(0, attempt_number - 1)), settings.retry_max_seconds)


async def deliver(event: Event) -> DeliveryAttempt:
    """Deliver to a deterministic local sink; no outbound requests are made."""
    import json

    payload = json.loads(event.payload)
    mode = payload.get("simulate", "success")
    number = event.attempts + 1
    event.attempts = number
    now = datetime.now(timezone.utc)
    event.updated_at = now
    if mode == "transient" and number == 1:
        event.status = "retry_wait"
        event.last_error = "Simulated temporary sink outage"
        event.next_attempt_at = now + timedelta(seconds=retry_delay(number))
        attempt = DeliveryAttempt(event=event, attempt_number=number, outcome="retryable_failure", message=event.last_error)
    elif mode == "permanent":
        event.status = "dead_letter"
        event.last_error = "Simulated permanent sink rejection"
        event.next_attempt_at = None
        attempt = DeliveryAttempt(event=event, attempt_number=number, outcome="permanent_failure", message=event.last_error)
    elif mode == "transient" and number > 1:
        event.status = "delivered"
        event.last_error = ""
        event.next_attempt_at = None
        attempt = DeliveryAttempt(event=event, attempt_number=number, outcome="success", message="Delivered to local demo sink after retry")
    else:
        event.status = "delivered"
        event.last_error = ""
        event.next_attempt_at = None
        attempt = DeliveryAttempt(event=event, attempt_number=number, outcome="success", message="Delivered to local demo sink")
    return attempt
