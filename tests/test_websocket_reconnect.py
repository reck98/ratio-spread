from unittest.mock import AsyncMock, patch

import pytest

from broker.websocket_client import WebSocketManager


@pytest.mark.asyncio
async def test_reconnect_succeeds_first_attempt() -> None:
    ws_mgr = WebSocketManager(access_token="test_token")
    ws_mgr._running = True
    ws_mgr._subscribed = {"NSE_FO|NIFTY24CE", "NSE_FO|NIFTY24PE"}

    with patch.object(ws_mgr, "_close_socket", new_callable=AsyncMock) as mock_close, \
         patch.object(ws_mgr, "connect", new_callable=AsyncMock) as mock_connect, \
         patch.object(ws_mgr, "subscribe", new_callable=AsyncMock) as mock_sub, \
         patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:

        result = await ws_mgr._reconnect()

        assert result is True
        mock_close.assert_called_once()
        mock_connect.assert_called_once()
        mock_sub.assert_called_once()
        assert set(mock_sub.call_args[0][0]) == {"NSE_FO|NIFTY24CE", "NSE_FO|NIFTY24PE"}
        mock_sleep.assert_called_once_with(2)  # attempt 1 delay: 2s


@pytest.mark.asyncio
async def test_reconnect_indefinite_after_five_attempts() -> None:
    ws_mgr = WebSocketManager(access_token="test_token")
    ws_mgr._running = True
    ws_mgr._subscribed = set()

    connect_attempts = 0

    async def mock_connect_side_effect() -> None:
        nonlocal connect_attempts
        connect_attempts += 1
        if connect_attempts < 7:
            raise RuntimeError(f"Connection failed attempt {connect_attempts}")

    delays: list[int] = []

    async def mock_sleep_side_effect(delay: int) -> None:
        delays.append(delay)

    with patch.object(ws_mgr, "_close_socket", new_callable=AsyncMock), \
         patch.object(ws_mgr, "connect", side_effect=mock_connect_side_effect), \
         patch("asyncio.sleep", side_effect=mock_sleep_side_effect):

        result = await ws_mgr._reconnect()

        assert result is True
        assert connect_attempts == 7
        # Delays for attempts 1..5 should be 2, 4, 6, 8, 10
        # Delays for attempts 6, 7 should be 15, 15
        assert delays == [2, 4, 6, 8, 10, 15, 15]


@pytest.mark.asyncio
async def test_reconnect_stops_when_not_running() -> None:
    ws_mgr = WebSocketManager(access_token="test_token")
    ws_mgr._running = True

    async def mock_sleep_stop(delay: int) -> None:
        ws_mgr._running = False

    with patch.object(ws_mgr, "_close_socket", new_callable=AsyncMock), \
         patch.object(ws_mgr, "connect", side_effect=RuntimeError("Fail")), \
         patch("asyncio.sleep", side_effect=mock_sleep_stop):

        result = await ws_mgr._reconnect()

        assert result is False
