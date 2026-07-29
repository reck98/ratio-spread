import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from broker.MarketDataFeed_pb2 import Feed, FeedResponse
from broker.MarketDataFeed_pb2 import Type as FeedType
from utils.logging import LogManager
from utils.models import BrokerHealth, Tick


class WebSocketManager:
    BASE_URL = "https://api.upstox.com/v3"
    AUTHORIZE_PATH = "/feed/market-data-feed/authorize"

    def __init__(self, access_token: str) -> None:
        self._access_token = access_token
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._subscribed: set[str] = set()
        self._running = False
        self._health = BrokerHealth.DISCONNECTED
        self._on_tick: Optional[Callable[[Tick], Awaitable[None]]] = None
        self._on_disconnect: Optional[Callable[[], None]] = None
        self._logger = LogManager.get_logger("websocket")
        self._last_heartbeat: Optional[datetime] = None
        self._heartbeat_timeout = 30
        self._max_reconnect_attempts = 5
        self._reconnect_backoff_base = 2
        # Cap incoming frame size (4 MiB) so a malformed/huge feed frame can't drive
        # unbounded memory allocation.
        self._max_msg_size = 4 * 1024 * 1024

    @property
    def health(self) -> BrokerHealth:
        return self._health

    def set_tick_handler(self, handler: Callable[[Tick], Awaitable[None]]) -> None:
        self._on_tick = handler

    def set_disconnect_handler(self, handler: Callable[[], None]) -> None:
        self._on_disconnect = handler

    async def _get_authorized_url(self) -> str:
        assert self._session is not None
        url = f"{self.BASE_URL}{self.AUTHORIZE_PATH}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        async with self._session.get(url, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Authorize failed: {resp.status} {text}")
            data = await resp.json()
        redirect_uri = data.get("data", {}).get("authorized_redirect_uri")
        if not redirect_uri:
            raise RuntimeError("No authorized_redirect_uri in response")
        self._logger.info("Got authorized WebSocket URL")
        return str(redirect_uri)

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession()
        try:
            ws_url = await self._get_authorized_url()
            headers = {"Authorization": f"Bearer {self._access_token}"}
            self._ws = await self._session.ws_connect(
                ws_url, headers=headers, heartbeat=10, max_msg_size=self._max_msg_size,
            )
            self._health = BrokerHealth.CONNECTED
            self._last_heartbeat = datetime.now(timezone.utc)
            self._logger.info("WebSocket connected")
        except Exception as e:
            await self._session.close()
            self._session = None
            self._health = BrokerHealth.FAILED
            self._logger.error("WebSocket connection failed: %s", e)
            raise

    async def subscribe(self, instrument_keys: list[str]) -> None:
        if not self._ws:
            self._logger.warning("WebSocket not connected, cannot subscribe")
            return

        new_keys = [k for k in instrument_keys if k not in self._subscribed]
        if not new_keys:
            return

        payload = {
            "guid": "feed",
            "method": "sub",
            "data": {
                "mode": "ltpc",
                "instrumentKeys": new_keys,
            },
        }
        await self._ws.send_bytes(json.dumps(payload).encode())
        for k in new_keys:
            self._subscribed.add(k)
        self._logger.info("Subscribed to %d instruments: %s", len(new_keys), new_keys)

    async def listen(self) -> None:
        self._running = True
        # Supervisory loop: on any recoverable break we reconnect and keep listening
        # instead of returning, so the feed survives more than one disconnect.
        while self._running:
            if not self._ws:
                if not await self._reconnect():
                    break
                continue
            try:
                msg = await self._ws.receive(timeout=self._heartbeat_timeout)
                if msg.type == aiohttp.WSMsgType.BINARY:
                    self._last_heartbeat = datetime.now(timezone.utc)
                    await self._process_message(msg.data)
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    self._last_heartbeat = datetime.now(timezone.utc)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    self._logger.warning("WebSocket closed by server, reconnecting")
                    if not await self._reconnect():
                        break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self._logger.warning("WebSocket error: %s", self._ws.exception())
                    if not await self._reconnect():
                        break
            except asyncio.TimeoutError:
                elapsed = (
                    (datetime.now(timezone.utc) - self._last_heartbeat).total_seconds()
                    if self._last_heartbeat else 0
                )
                if self._last_heartbeat and elapsed > self._heartbeat_timeout:
                    self._logger.warning("Heartbeat timeout, reconnecting")
                    if not await self._reconnect():
                        break
            except Exception as e:
                self._logger.error("WebSocket listen error: %s", e)
                if not await self._reconnect():
                    break

    async def _process_message(self, data: bytes) -> None:
        response = FeedResponse()
        try:
            response.ParseFromString(data)
        except Exception as e:
            self._logger.warning("Failed to parse protobuf: %s", e)
            return

        if response.type == FeedType.market_info:
            return

        if response.type != FeedType.live_feed:
            return

        for instrument_key, feed in response.feeds.items():
            ltp = self._extract_ltp(feed)
            if ltp is not None:
                tick = Tick(
                    instrument_key=instrument_key,
                    ltp=float(ltp),
                    timestamp=datetime.now(timezone.utc),
                )
                if self._on_tick:
                    await self._on_tick(tick)

    @staticmethod
    def _extract_ltp(feed: Feed) -> Optional[float]:
        field = feed.WhichOneof("FeedUnion")
        if field == "ltpc":
            return feed.ltpc.ltp
        if field == "fullFeed":
            ff = feed.fullFeed
            inner = ff.WhichOneof("FullFeedUnion")
            if inner == "marketFF":
                return ff.marketFF.ltpc.ltp
            if inner == "indexFF":
                return ff.indexFF.ltpc.ltp
        if field == "firstLevelWithGreeks":
            return feed.firstLevelWithGreeks.ltpc.ltp
        return None

    async def _close_socket(self) -> None:
        """Tear down the current socket/session WITHOUT stopping the listen loop."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                self._logger.warning("Error closing websocket: %s", e)
            self._ws = None
        if self._session:
            try:
                await self._session.close()
            except Exception as e:
                self._logger.warning("Error closing session: %s", e)
            self._session = None

    async def _reconnect(self) -> bool:
        """Reconnect with bounded backoff for initial 5 attempts, then retry every 15s indefinitely.

        Does NOT flip ``_running`` off, so the supervisory ``listen`` loop keeps
        running and re-subscribes after every disconnect.
        """
        self._health = BrokerHealth.RECONNECTING
        await self._close_socket()

        # Re-subscribe from scratch on the fresh socket.
        keys_to_resubscribe = list(self._subscribed)
        self._subscribed.clear()

        attempt = 1
        while self._running:
            if attempt <= self._max_reconnect_attempts:
                delay = self._reconnect_backoff_base * attempt
                self._logger.info(
                    "Reconnection attempt %d/%d in %ds...",
                    attempt, self._max_reconnect_attempts, delay,
                )
            else:
                delay = 15
                self._logger.info(
                    "Reconnection attempt %d (indefinite mode) in %ds...",
                    attempt, delay,
                )
            await asyncio.sleep(delay)
            if not self._running:
                return False
            try:
                await self.connect()
                if keys_to_resubscribe:
                    await self.subscribe(keys_to_resubscribe)
                if self._on_disconnect:
                    self._on_disconnect()
                self._logger.info("Reconnection succeeded on attempt %d", attempt)
                return True
            except Exception as e:
                self._logger.error("Reconnection attempt %d failed: %s", attempt, e)
            attempt += 1

        return False

    async def disconnect(self) -> None:
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._session:
            await self._session.close()
            self._session = None
        self._health = BrokerHealth.DISCONNECTED
        self._logger.info("WebSocket disconnected")
