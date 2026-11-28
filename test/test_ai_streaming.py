"""The shared SSE writer and stream lifecycle."""

from __future__ import annotations

import pytest

from recipeserver.ai_streaming import EventStream, StreamClosed, run_stream


class _Wfile:
    def __init__(self, fail: bool = False) -> None:
        self.chunks: list[bytes] = []
        self.fail = fail
        self.flushed = False

    def write(self, chunk: bytes) -> None:
        if self.fail:
            raise BrokenPipeError("closed")
        self.chunks.append(chunk)

    def flush(self) -> None:
        self.flushed = True

    def text(self) -> str:
        return b"".join(self.chunks).decode("utf-8")


class _Responder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.close_connection = False

    def send_response(self, status: int) -> None:
        self.calls.append(("status", status))

    def send_header(self, name: str, value: str) -> None:
        self.calls.append(("header", name, value))

    def end_headers(self) -> None:
        self.calls.append(("end",))


def _run(generate, *, fail: bool = False, expected=(ValueError,)):
    wfile = _Wfile(fail=fail)
    responder = _Responder()
    run_stream(
        wfile=wfile,
        responder=responder,
        generate=generate,
        expected_exceptions=expected,
        error_event="error",
        error_state="error",
        result_event="result",
        label="test stream",
    )
    return wfile, responder


def test_begin_writes_headers_and_closes_the_connection():
    wfile, responder = _run(lambda send: {"ok": True})
    assert ("status", 200) in responder.calls
    assert ("header", "Content-Type", "text/event-stream; charset=utf-8") in responder.calls
    assert ("header", "X-Accel-Buffering", "no") in responder.calls
    assert ("end",) in responder.calls
    assert responder.close_connection is True
    assert wfile.flushed
    assert "event: result" in wfile.text()
    assert 'data: {"type": "result", "result": {"ok": true}}' in wfile.text()


def test_send_emits_browser_compatible_frames_and_rejects_newlines_in_type():
    wfile = _Wfile()
    EventStream(wfile).send({"type": "sta\ntus", "message": "hi"})
    assert wfile.text().startswith("event: status\ndata: ")
    assert wfile.text().endswith("\n\n")


def test_closed_connection_becomes_stream_closed():
    with pytest.raises(StreamClosed):
        EventStream(_Wfile(fail=True)).send({"type": "status"})


def test_expected_failure_is_reported_as_an_error_event():
    def generate(send):
        send({"type": "status", "message": "thinking"})
        raise ValueError("bad input")

    wfile, _ = _run(generate)
    body = wfile.text()
    assert "event: status" in body
    assert "event: error" in body
    assert "bad input" in body
    assert "event: result" not in body


def test_unexpected_failure_is_generic_and_disconnect_is_quiet():
    def boom(send):
        raise RuntimeError("secret detail")

    wfile, _ = _run(boom)
    assert "event: error" in wfile.text()
    assert "secret detail" not in wfile.text()

    def disconnect(send):
        raise StreamClosed

    wfile, _ = _run(disconnect)
    assert wfile.text() == ""
