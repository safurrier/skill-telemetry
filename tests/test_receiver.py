from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from skill_telemetry.receiver import read_request_body


class _Headers:
    def __init__(self, values: dict[str, list[str]]) -> None:
        self.values = values

    def get_all(self, name: str, default: list[str]) -> list[str]:
        return self.values.get(name, default)


def _handler(headers: dict[str, list[str]], body: bytes) -> SimpleNamespace:
    return SimpleNamespace(headers=_Headers(headers), rfile=BytesIO(body))


def test_receiver_reads_content_length_and_chunked_bodies() -> None:
    assert read_request_body(_handler({"Content-Length": ["3"]}, b"abc"), 3) == b"abc"
    assert (
        read_request_body(
            _handler({"Transfer-Encoding": ["chunked"]}, b"3\r\nabc\r\n0\r\n\r\n"), 3
        )
        == b"abc"
    )


@pytest.mark.parametrize(
    ("headers", "body"),
    [
        ({"Content-Length": ["3"], "Transfer-Encoding": ["chunked"]}, b"abc"),
        ({"Content-Length": ["4"]}, b"abc"),
        ({"Transfer-Encoding": ["gzip"]}, b""),
    ],
)
def test_receiver_rejects_ambiguous_truncated_or_unsupported_framing(
    headers: dict[str, list[str]], body: bytes
) -> None:
    with pytest.raises(ValueError):
        read_request_body(_handler(headers, body), 10)
