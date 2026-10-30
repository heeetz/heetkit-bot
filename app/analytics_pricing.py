"""Dated, conservative USD estimates from reported usage, never billing totals.

Snapshot checked 2026-10-30, standard paid text rates per million tokens:
https://developers.openai.com/api/docs/models/gpt-4.1-mini
https://developers.openai.com/api/docs/pricing
https://ai.google.dev/gemini-api/docs/pricing
Unsupported models/tiers/tools remain explicitly incomplete. DeepSeek's changing
peak/holiday schedule and retired aliases have no rate in this snapshot.
"""

from datetime import date

PRICE_CHECKED = "2026-10-30"
# Input, cached input, output. Output already includes reasoning tokens.
RATES = {
    ("openai", "gpt-4.1-mini"): (0.40, 0.10, 1.60),
    ("openai", "gpt-4.1-mini-2025-04-14"): (0.40, 0.10, 1.60),
    ("gemini", "gemini-2.5-flash"): (0.30, 0.03, 2.50),
    ("gemini", "gemini-2.5-flash-lite"): (0.10, 0.01, 0.40),
}


def estimate(provider, model, usage, at):
    rates = RATES.get((provider, model))
    if rates is None or at.date() < date.fromisoformat(PRICE_CHECKED):
        return None, True
    incoming, outgoing, cached = (usage.get(key) for key in ("input_tokens", "output_tokens", "cached_input_tokens"))
    valid = lambda value: type(value) is int and value >= 0
    if not valid(incoming) and not valid(outgoing):
        return None, True
    incomplete = (not valid(incoming) or not valid(outgoing) or not valid(cached)
                  or bool(usage.get("usage_incomplete")) or provider == "gemini")
    cost = outgoing * rates[2] if valid(outgoing) else 0
    if valid(incoming):
        if valid(cached) and cached <= incoming:
            cost += (incoming - cached) * rates[0] + cached * rates[1]
        elif valid(cached):
            incomplete = True
        else:
            # Cache amount unknown: do not invent a cache miss count.
            incomplete = True
    # Standard OpenAI web-search tool calls have a known $10/1k fee. Content
    # billing cannot safely be separated from input totals, so keep it incomplete.
    searches = usage.get("search_requests")
    if provider == "openai" and valid(searches):
        cost += searches * 10_000  # cost is still in millionths of USD here.
    if usage.get("search_requested") or searches:
        incomplete = True
    return cost / 1_000_000, incomplete
