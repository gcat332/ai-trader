# tests/test_skill_loader.py
import pytest
from pathlib import Path
from strategy.ml.skill_loader import load_trading_skills, SKILL_ORDER


def test_skill_order_has_seven_skills():
    assert len(SKILL_ORDER) == 7


def test_load_skills_returns_string():
    prompt = load_trading_skills()
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_load_skills_contains_all_skill_names():
    prompt = load_trading_skills()
    for keyword in ["RSI", "MACD", "ADX", "confidence", "stop_loss", "HOLD", "checklist"]:
        assert keyword in prompt, f"Expected '{keyword}' in combined skills prompt"


def test_load_skills_self_review_is_last():
    prompt = load_trading_skills()
    hold_idx = prompt.rfind("Self-Review")
    risk_idx = prompt.rfind("Risk Discipline")
    assert hold_idx > risk_idx, "self_review must appear after risk_discipline"


def test_load_skills_custom_subset():
    prompt = load_trading_skills(skills=["market_reading", "risk_discipline"])
    assert "RSI" in prompt
    assert "stop_loss" in prompt
    # self_review not loaded in custom subset
    assert "checklist" not in prompt
