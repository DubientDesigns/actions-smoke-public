"""Claude API list prices (US$ per million tokens), first-party API.

Source: the bundled claude-api reference (cached 2026-10-06). Verify on
https://platform.claude.com/docs/en/about-claude/pricing before budgeting.
Haiku 5.5 has two rate cards selected by prompt length (<=100K vs >100K).
Cache reads bill at 0.1x input; 5-minute cache writes at 1.25x input.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    long_input: float | None = None  # rate card above LONG_PROMPT_TOKENS
    long_output: float | None = None


LONG_PROMPT_TOKENS = 100_000

PRICES: dict[str, Price] = {
    "claude-haiku-5-5": Price(0.10, 0.50, 0.50, 2.50),
    "claude-sonnet-5-5": Price(2.00, 10.00),
    "claude-opus-5-5": Price(4.00, 20.00),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
    p = PRICES.get(model)
    if p is None:
        raise KeyError(f"no price configured for {model}; add it to cit/ai/pricing.py before use")
    prompt = input_tokens + cache_read + cache_write
    long = p.long_input is not None and prompt > LONG_PROMPT_TOKENS
    pin = p.long_input if long and p.long_input is not None else p.input
    pout = p.long_output if long and p.long_output is not None else p.output
    return (input_tokens * pin + cache_read * pin * 0.1 + cache_write * pin * 1.25 + output_tokens * pout) / 1e6


def worst_case_usd(model: str, est_input_tokens: int, max_output_tokens: int) -> float:
    """Upper bound used by the budget gate before a call is made."""
    return cost_usd(model, est_input_tokens, max_output_tokens)
