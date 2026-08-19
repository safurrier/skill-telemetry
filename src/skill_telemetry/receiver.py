"""Neutral privacy-first loopback HTTP ingestion substrate.

Raw request bodies are bounded and live only for the duration of adapter dispatch.
This module deliberately has no dependency on any retained telemetry contract.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Protocol

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 14318
DEFAULT_MAX_REQUEST_BYTES = 2 * 1024 * 1024
MAX_CHUNK_HEADER_BYTES = 128
MAX_CHUNKS = 4096
REQUEST_READ_TIMEOUT_SECONDS = 5
CHUNK_SIZE_RE = re.compile(rb"^[0-9A-Fa-f]+$")
CONTENT_LENGTH_RE = re.compile(r"^[0-9]+$")
DOMAIN_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """Content-safe result returned by one endpoint adapter."""

    response_body: bytes
    accepted_counts: tuple[tuple[str, int], ...] = ()
    content_type: str = "application/x-protobuf"

    def __post_init__(self) -> None:
        for domain, count in self.accepted_counts:
            if not DOMAIN_NAME_RE.fullmatch(domain):
                raise ValueError("adapter returned an invalid domain name")
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("adapter returned an invalid accepted count")


class AdapterPayloadError(ValueError):
    """Raised when an adapter cannot parse or normalize the request payload."""


class AdapterInfrastructureError(RuntimeError):
    """Raised when a normalized request cannot be persisted safely."""


@dataclass(frozen=True, slots=True)
class PreparedAdapterResult:
    """A fully normalized domain batch whose commit has no payload parsing left to do."""

    response_body: bytes
    commit: Callable[[], tuple[tuple[str, int], ...]]
    content_type: str = "application/x-protobuf"


class EndpointAdapter(Protocol):
    """Typed boundary implemented by explicit endpoint adapters."""

    def ingest(self, payload: bytes, content_type: str) -> AdapterResult:
        """Consume one in-memory envelope and return only sanitized counts/bytes."""


class PreflightAdapter(Protocol):
    """Domain adapter that separates payload preflight from persistence."""

    def prepare(self, payload: bytes, content_type: str) -> PreparedAdapterResult:
        """Parse and normalize the complete payload without writing retained state."""


class CompositeEndpointAdapter:
    """Preflight every domain before committing in deterministic adapter order.

    Persistence is intentionally at-least-once rather than cross-store transactional.
    A failure stops later domains but may leave a prefix in the failing domain. A
    retry is safe because each store deduplicates its own stable fingerprints.
    """

    def __init__(self, *adapters: PreflightAdapter) -> None:
        if not adapters:
            raise ValueError("composite endpoint requires at least one adapter")
        self.adapters = adapters

    def ingest(self, payload: bytes, content_type: str) -> AdapterResult:
        prepared = tuple(
            adapter.prepare(payload, content_type) for adapter in self.adapters
        )
        response_body = prepared[0].response_body
        response_content_type = prepared[0].content_type
        if any(
            item.response_body != response_body
            or item.content_type != response_content_type
            for item in prepared[1:]
        ):
            raise RuntimeError("endpoint adapters returned incompatible responses")

        accepted: dict[str, int] = {}
        for item in prepared:
            for domain, count in item.commit():
                accepted[domain] = accepted.get(domain, 0) + count
        return AdapterResult(
            response_body=response_body,
            accepted_counts=tuple(sorted(accepted.items())),
            content_type=response_content_type,
        )


def read_chunked_body(handler: BaseHTTPRequestHandler, max_bytes: int) -> bytes:
    """Read a bounded HTTP/1.1 chunked body without accepting trailers."""
    chunks: list[bytes] = []
    total = 0
    while True:
        header = handler.rfile.readline(MAX_CHUNK_HEADER_BYTES + 1)
        if len(header) > MAX_CHUNK_HEADER_BYTES or not header.endswith(b"\r\n"):
            raise ValueError("invalid chunk header")
        size_text = header[:-2].split(b";", 1)[0]
        if not CHUNK_SIZE_RE.fullmatch(size_text):
            raise ValueError("invalid chunk size")
        size = int(size_text, 16)
        if size == 0:
            if handler.rfile.readline(MAX_CHUNK_HEADER_BYTES + 1) != b"\r\n":
                raise ValueError("chunk trailers are not supported")
            return b"".join(chunks)
        if len(chunks) >= MAX_CHUNKS:
            raise OverflowError("request has too many chunks")
        total += size
        if total > max_bytes:
            raise OverflowError("request body exceeds configured limit")
        chunk = handler.rfile.read(size)
        if len(chunk) != size or handler.rfile.read(2) != b"\r\n":
            raise ValueError("truncated chunk body")
        chunks.append(chunk)


def read_request_body(handler: BaseHTTPRequestHandler, max_bytes: int) -> bytes:
    """Read one bounded body from either Content-Length or chunked framing."""
    length_values = handler.headers.get_all("Content-Length", [])
    transfer_values = handler.headers.get_all("Transfer-Encoding", [])
    if len(length_values) > 1 or len(transfer_values) > 1:
        raise ValueError("duplicate request framing headers")
    length_header = length_values[0] if length_values else None
    transfer_encoding = transfer_values[0] if transfer_values else None
    if length_header is not None and transfer_encoding is not None:
        raise ValueError("ambiguous request framing")
    if transfer_encoding is not None:
        if transfer_encoding.strip().lower() != "chunked":
            raise ValueError("unsupported transfer encoding")
        return read_chunked_body(handler, max_bytes)
    if length_header is None:
        raise ValueError("content length required")
    if not CONTENT_LENGTH_RE.fullmatch(length_header):
        raise ValueError("invalid content length")
    length = int(length_header)
    if length > max_bytes:
        raise OverflowError("request body exceeds configured limit")
    payload = handler.rfile.read(length)
    if len(payload) != length:
        raise ValueError("truncated request body")
    return payload


class ReceiverServer(ThreadingHTTPServer):
    """No-export receiver that refuses non-loopback bind addresses."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        adapters: dict[str, EndpointAdapter],
        *,
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    ) -> None:
        try:
            address = ipaddress.ip_address(server_address[0])
        except ValueError as exc:
            raise ValueError(
                "receiver host must be a literal loopback address"
            ) from exc
        if not address.is_loopback:
            raise ValueError("receiver may bind only to loopback")
        if any(not path.startswith("/") for path in adapters):
            raise ValueError("adapter paths must be absolute")
        self.endpoint_adapters = dict(adapters)
        self.max_request_bytes = max_request_bytes
        super().__init__(server_address, ReceiverHandler)


class ReceiverHandler(BaseHTTPRequestHandler):
    """Bounded HTTP request handler with explicit path-to-adapter dispatch."""

    server: ReceiverServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(REQUEST_READ_TIMEOUT_SECONDS)

    def do_GET(self) -> None:
        if self.path != "/healthz":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = json.dumps(
            {
                "status": "ok",
                "bind": "loopback",
                "external_export": False,
                "schema_version": 1,
            }
        ).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        adapter = self.server.endpoint_adapters.get(self.path)
        if adapter is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = read_request_body(self, self.server.max_request_bytes)
        except OverflowError:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return
        except TimeoutError:
            self.send_error(HTTPStatus.REQUEST_TIMEOUT)
            return
        except (OSError, ValueError):
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        try:
            result = adapter.ingest(payload, self.headers.get("Content-Type", ""))
        except AdapterPayloadError:
            self.send_error(HTTPStatus.BAD_REQUEST)
            return
        except (AdapterInfrastructureError, OSError):
            self.send_error(HTTPStatus.SERVICE_UNAVAILABLE)
            return
        except (RuntimeError, TypeError, ValueError):
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", result.content_type)
        self.send_header("Content-Length", str(len(result.response_body)))
        for domain, count in result.accepted_counts:
            self.send_header(f"X-{domain.title()}-Telemetry-Accepted", str(count))
        self.end_headers()
        self.wfile.write(result.response_body)

    def log_message(self, format: str, *args: object) -> None:
        """Avoid writing request-derived content to stdout or logs."""
        _ = (format, args)
