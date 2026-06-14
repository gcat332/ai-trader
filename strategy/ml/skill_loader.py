# strategy/ml/skill_loader.py
from pathlib import Path

_SKILLS_DIR = Path(__file__).parent / "skills"

SKILL_ORDER = [
    "market_reading",
    "signal_synthesis",
    "risk_discipline",
    "confidence_calibration",
    "regime_detection",
    "position_context",
    "self_review",         # always last — runs as final sanity check
]


def load_trading_skills(skills: list[str] | None = None) -> str:
    """Load and concatenate skill files into a single system prompt string."""
    names = skills if skills is not None else SKILL_ORDER
    sections = []
    for name in names:
        path = _SKILLS_DIR / f"{name}.md"
        sections.append(path.read_text(encoding="utf-8").strip())
    return "\n\n---\n\n".join(sections)
