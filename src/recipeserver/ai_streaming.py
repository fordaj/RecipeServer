"""Server-Sent Events framing and stream endpoint orchestration.

Both AI endpoints (recipe drafting and the assistant) stream the same JSON
events with the same wire format and the same terminal-event behavior. This
module owns that framing; the HTTP handler supplies the response object and
the domain generator, and keeps its own routing and non-stream responses.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from ._logger import logger
from .recipe_utils import json_default

EVENT_MESSAGE = "message"


class StreamClosed(Exception):
    """The browser closed the stream while an event was being written."""


class EventStream:
    """Write one SSE response, converting a closed connection to ``StreamClosed``."""

    def __init__(self, wfile) -> None:
        self._wfile = wfile

    def begin(self, responder) -> None:
        responder.send_response(200)
        responder.send_header("Content-Type", "text/event-stream; charset=utf-8")
        responder.send_header("Cache-Control", "no-store")
        responder.send_header("Connection", "close")
        responder.send_header("X-Accel-Buffering", "no")
        responder.end_headers()
        responder.close_connection = True

    def send(self, event: dict) -> None:
        event_type = str(event.get("type", EVENT_MESSAGE)).replace("\n", "")
        body = json.dumps(event, default=json_default).encode("utf-8")
        try:
            self._wfile.write(f"event: {event_type}\n".encode("utf-8"))
            self._wfile.write(b"data: " + body + b"\n\n")
            self._wfile.flush()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise StreamClosed from exc

    def error(self, event_type: str, state: str, message: str) -> None:
        self.send({"type": event_type, "state": state, "message": message})

    def result(self, event_type: str, result: dict) -> None:
        self.send({"type": event_type, "result": result})


def run_stream(
    *,
    wfile,
    responder,
    generate: Callable[[Callable[[dict], None]], dict],
    expected_exceptions: tuple[type[Exception], ...],
    error_event: str,
    error_state: str,
    result_event: str,
    label: str,
) -> None:
    """Run one streamed AI endpoint through a single, shared event lifecycle.

    ``generate`` receives the stream's ``send`` callback. Expected domain
    failures are reported as an error event, unexpected ones as a generic
    error, and a successful result as the terminal result event. A browser that
    disconnects ends the stream quietly.
    """
    stream = EventStream(wfile)
    stream.begin(responder)

    try:
        result = generate(stream.send)
    except StreamClosed:
        logger.debug(f"{label} stream closed by the browser")
        return
    except expected_exceptions as exc:
        logger.warning(f"{label} failed: {exc}")
        _send_quietly(stream, lambda: stream.error(error_event, error_state, str(exc)))
        return
    except Exception:
        logger.exception(f"Unexpected failure in {label}")
        _send_quietly(stream, lambda: stream.error(error_event, error_state, f"Unable to complete {label}"))
        return

    logger.info(f"{label} succeeded")
    _send_quietly(stream, lambda: stream.result(result_event, result))


def _send_quietly(stream: EventStream, send: Callable[[], None]) -> None:
    try:
        send()
    except StreamClosed:
        logger.debug("AI result was not delivered because the browser closed the stream")
