"""Bounded HTTP transport and conservative, robots-aware fetching."""
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
import time
import math
from typing import Protocol
from urllib.error import HTTPError
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

MAX_BYTES = 5 * 1024 * 1024


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict = field(default_factory=dict)

    def header(self, name, default=''):
        return next((v for k, v in self.headers.items() if k.lower() == name.lower()), default)

    def text(self):
        return self.body.decode('utf-8-sig', errors='replace')


class Transport(Protocol):
    def request(self, url: str, user_agent: str, timeout: float) -> Response: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibTransport:
    def request(self, url, user_agent, timeout):
        opener = build_opener(NoRedirect())
        try:
            result = opener.open(Request(url, headers={'User-Agent': user_agent}), timeout=timeout)
        except HTTPError as exc:
            result = exc
        with result:
            body = result.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise ValueError('response exceeds 5 MB')
            return Response(result.code, body, dict(result.headers))


class FakeTransport:
    """Scripted responses or exceptions; never falls back to the network."""
    def __init__(self, routes):
        self.routes = {k: list(v) if isinstance(v, list) else [v] for k, v in routes.items()}
        self.calls = []

    def request(self, url, user_agent, timeout):
        self.calls.append((url, user_agent, timeout))
        values = self.routes.get(url, [Response(404, b'')])
        value = values.pop(0) if len(values) > 1 else values[0]
        if isinstance(value, Exception):
            raise value
        return value


class Fetcher:
    def __init__(self, transport, user_agent='SeoAuditGate', interval_ms=1000,
                 timeout=30, retries=3, sleep=time.sleep, clock=time.monotonic,
                 wall_clock=time.time):
        self.transport = transport
        self.user_agent = user_agent
        self.interval = interval_ms / 1000
        self.timeout = timeout
        self.retries = retries
        self.sleep, self.clock, self.wall_clock = sleep, clock, wall_clock
        self.last = {}
        self.domain_intervals = {}
        self.robots = {}
        self.robots_bodies = {}

    def _request(self, url):
        domain = urlsplit(url).hostname
        for attempt in range(self.retries + 1):
            if domain in self.last:
                interval = max(self.interval, self.domain_intervals.get(domain, 0))
                self.sleep(max(0, interval - (self.clock() - self.last[domain])))
            self.last[domain] = self.clock()
            try:
                response = self.transport.request(url, self.user_agent, self.timeout)
                if len(response.body) > MAX_BYTES:
                    return None
            except (OSError, ValueError):
                response = None
            if response is not None and response.status != 429 and not 500 <= response.status <= 599:
                return response
            if attempt == self.retries:
                return None
            delay = 2 ** attempt
            if response is not None:
                retry = response.header('Retry-After')
                try:
                    seconds = float(retry)
                    if math.isfinite(seconds):
                        delay = max(delay, seconds)
                except (ValueError, TypeError):
                    try:
                        delay = max(delay, parsedate_to_datetime(retry).timestamp() - self.wall_clock())
                    except (ValueError, TypeError, OverflowError):
                        pass
            self.sleep(delay)
        return None

    def _allowed(self, url):
        parts = urlsplit(url)
        origin = f'{parts.scheme}://{parts.netloc}'
        if origin not in self.robots:
            response = self._request(origin + '/robots.txt')
            parser = None
            if response is not None and response.status == 200:
                try:
                    text = response.body.decode('utf-8-sig')
                    parser = RobotFileParser()
                    parser.parse(text.splitlines())
                    self.robots_bodies[origin] = response.body
                    delay = parser.crawl_delay(self.user_agent) or 0
                    rate = parser.request_rate(self.user_agent)
                    if rate and rate.requests > 0:
                        delay = max(delay, rate.seconds / rate.requests)
                    self.domain_intervals[parts.hostname] = max(
                        delay, self.domain_intervals.get(parts.hostname, 0))
                except UnicodeError:
                    parser = None
            self.robots[origin] = parser
        parser = self.robots[origin]
        return parser is not None and parser.can_fetch(self.user_agent, url)

    def fetch(self, url):
        """Redirects stay on the starting host; every hop needs robots permission."""
        host = urlsplit(url).netloc.lower()
        for _ in range(6):
            parts = urlsplit(url)
            if (parts.scheme not in ('http', 'https') or parts.netloc.lower() != host
                    or parts.username is not None or not self._allowed(url)):
                return None
            response = self._request(url)
            if response is None:
                return None
            if response.status in (301, 302, 303, 307, 308):
                location = response.header('Location')
                if not location:
                    return None
                url = urljoin(url, location)
                continue
            return (url, response) if response.status == 200 else None
        return None
