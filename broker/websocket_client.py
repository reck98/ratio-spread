import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import aiohttp

from utils.logging import LogManager
from utils.models import BrokerHealth, Tick


class WebSocketManager:
    def __init__(self, access_token: str) -> None:
        self._access_token = access_token
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._subscribed: set[str] = set()
        self._running = False
        self._health = BrokerHealth.DISCONNECTED
        self._on_tick: Optional[Callable[[Tick], None]] = None
        self._on_disconnect: Optional[Callable[[], None]] = None
        self._logger = LogManager.get_logger("websocket")
        self._last_heartbeat: Optional[datetime] = None
        self._heartbeat_timeout = 30

    @property
    def health(self) -> BrokerHealth:
        return self._health

    def set_tick_handler(self, handler: Callable[[Tick], None]) -> None:
        self._on_tick = handler

    def set_disconnect_handler(self, handler: Callable[[], None]) -> None:
        self._on_disconnect = handler

    async def connect(self) -> None:
        self._session = aiohttp.ClientSession()
        ws_url = "wss://api.upstox.com/v2/feed/market-data-feed/websocket"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        try:
            self._ws = await self._session.ws_connect(ws_url, headers=headers, heartbeat=10)
            self._health = BrokerHealth.CONNECTED
            self._last_heartbeat = datetime.now(timezone.utc)
            self._logger.info("WebSocket connected")
        except Exception as e:
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
                "instrumentKeys": new_keys,
            },
        }
        await self._ws.send_json(payload)
        for k in new_keys:
            self._subscribed.add(k)
        self._logger.info("Subscribed to %d instruments: %s", len(new_keys), new_keys)

    async def listen(self) -> None:
        self._running = True
        while self._running and self._ws:
            try:
                msg = await self._ws.receive(timeout=self._heartbeat_timeout)
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    self._last_heartbeat = datetime.now(timezone.utc)
                    self._process_message(data)
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    self._logger.warning("WebSocket closed by server")
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self._logger.error("WebSocket error: %s", self._ws.exception())
                    break
            except asyncio.TimeoutError:
                elapsed = (datetime.now(timezone.utc) - self._last_heartbeat).seconds if self._last_heartbeat else 0
                if self._last_heartbeat and elapsed > self._heartbeat_timeout:
                    self._logger.warning("Heartbeat timeout, reconnecting")
                    await self._reconnect()
                    break
            except Exception as e:
                self._logger.error("WebSocket listen error: %s", e)
                await self._reconnect()
                break

    def _process_message(self, data: dict[str, Any]) -> None:
        feeds = data.get("feeds", {})
        for instrument_key, feed in feeds.items():
            ff = feed.get("ff", {})
            ltp = ff.get("ltp", ff.get("marketData", {}).get("ltp"))
            if ltp is not None:
                tick = Tick(
                    instrument_key=instrument_key,
                    ltp=float(ltp),
                    timestamp=datetime.now(timezone.utc),
                )
                if self._on_tick:
                    self._on_tick(tick)

    async def _reconnect(self) -> None:
        self._health = BrokerHealth.RECONNECTING
        self._logger.info("Attempting reconnection...")
        await self.disconnect()
        await asyncio.sleep(2)
        try:
            await self.connect()
            if self._subscribed:
                await self.subscribe(list(self._subscribed))
            if self._on_disconnect:
                self._on_disconnect()
        except Exception as e:
            self._health = BrokerHealth.FAILED
            self._logger.error("Reconnection failed: %s", e)

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
