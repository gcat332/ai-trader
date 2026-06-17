from core.order_manager import OrderIntentStore


def test_order_intent_store_reuses_existing_intent_id_for_same_signal():
    store = OrderIntentStore()
    first = store.intent_id("loop1:ema_cross", "BTC/USDT", "decision-1")
    second = store.intent_id("loop1:ema_cross", "BTC/USDT", "decision-1")
    assert first == second


def test_order_intent_store_distinguishes_loops():
    store = OrderIntentStore()
    first = store.intent_id("loop1:ema_cross", "BTC/USDT", "decision-1")
    second = store.intent_id("loop2:ema_cross", "BTC/USDT", "decision-1")
    assert first != second
