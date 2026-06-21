from notifier.telegram import format_strategy_list, _format_position_line


def test_position_line_spot_unchanged():
    p = {"symbol": "BTC/USDT", "quantity": 0.1, "unrealized_pnl": 5.0, "mode": "SPOT"}
    line = _format_position_line(p)
    assert "BTC/USDT" in line and "0.1" in line and "5.0" in line
    assert "liq" not in line.lower()


def test_position_line_futures_shows_side_lev_liq_margin_first():
    p = {"symbol": "BTC/USDT", "quantity": 0.1, "unrealized_pnl": 8.0,
         "mode": "FUTURES", "side": "SHORT", "leverage": 3,
         "liquidation_price": 71240.0, "initial_margin": 2000.0}
    line = _format_position_line(p)
    assert "SHORT" in line
    assert "3x" in line
    assert "71,240" in line          # liq present
    assert "2,000" in line           # margin present
    # liq appears before pnl (survival number is skimmable)
    assert line.index("71,240") < line.index("8.0")


def test_strategy_list_labels_market():
    strategies = [{
        "loop_id": "loop3", "strategy_name": "trend", "mode": "LIVE",
        "market": "FUTURES", "running": True, "symbol": "BTC/USDT",
        "timeframe": "1h", "allocation_pct": 0.5, "open_order_count": 0,
        "open_positions": [],
    }]
    text = format_strategy_list(strategies)
    assert "FUTURES" in text
