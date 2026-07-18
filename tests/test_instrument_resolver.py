from unittest.mock import MagicMock

from broker.instrument_resolver import InstrumentResolver


def _make_resolver() -> InstrumentResolver:
    mock_broker = MagicMock()
    return InstrumentResolver(mock_broker)


def test_round_to_strike() -> None:
    resolver = _make_resolver()
    assert resolver.round_to_strike(25124) == 25100
    assert resolver.round_to_strike(25126) == 25150
    assert resolver.round_to_strike(25174) == 25150
    assert resolver.round_to_strike(25181) == 25200


def test_sell_strike_selection() -> None:
    resolver = _make_resolver()
    chain = [
        {"strike": 25200, "premium": 72},
        {"strike": 25250, "premium": 61},
        {"strike": 25300, "premium": 48},
        {"strike": 25350, "premium": 35},
    ]
    result = resolver.find_sell_strike(183, chain)
    assert result is not None
    assert result["premium"] <= 61.0
    assert result["strike"] == 25250


def test_sell_strike_edge_case() -> None:
    resolver = _make_resolver()
    chain = [
        {"strike": 25200, "premium": 64},
        {"strike": 25250, "premium": 58},
    ]
    result = resolver.find_sell_strike(180, chain)
    assert result is not None
    assert result["premium"] <= 60.0
    assert result["strike"] == 25250


def test_sell_strike_premium_too_small() -> None:
    resolver = _make_resolver()
    chain = [{"strike": 25200, "premium": 1}]
    result = resolver.find_sell_strike(2, chain)
    assert result is None


def test_sell_strike_no_match() -> None:
    resolver = _make_resolver()
    chain = [{"strike": 25200, "premium": 100}]
    result = resolver.find_sell_strike(50, chain)
    assert result is None


def test_sell_strike_respects_multiplier() -> None:
    # With sell_multiplier=2 the target is buy/2 = 90, so the 88-premium strike is the
    # highest that fits — a hardcoded /3 (target 60) would wrongly pick a lower one.
    resolver = _make_resolver()
    chain = [
        {"strike": 25200, "premium": 95},
        {"strike": 25250, "premium": 88},
        {"strike": 25300, "premium": 55},
    ]
    result = resolver.find_sell_strike(180, chain, sell_multiplier=2)
    assert result is not None
    assert result["strike"] == 25250

    # Same chain with the default multiplier of 3 (target 60) picks the lower strike.
    result3 = resolver.find_sell_strike(180, chain, sell_multiplier=3)
    assert result3 is not None
    assert result3["strike"] == 25300
