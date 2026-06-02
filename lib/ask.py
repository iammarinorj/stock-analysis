"""Claude API client with web_search tool support.

Usage:
  from lib import ask
  if ask.is_configured():
      for chunk in ask.ask_claude_stream(messages, system="...", search=True):
          print(chunk, end="")

Setup: add ANTHROPIC_API_KEY to .streamlit/secrets.toml (see example file).
"""
from __future__ import annotations

import os
from typing import Iterator

import streamlit as st


DEFAULT_MODEL = "claude-haiku-4-5-20251001"
SMART_MODEL = "claude-sonnet-4-6"

MODEL_LABELS = {
    DEFAULT_MODEL: "Haiku (fast, cheap — ~$0.001/q)",
    SMART_MODEL: "Sonnet (smarter, ~$0.01-0.05/q)",
    "claude-opus-4-6": "Opus (deepest, slowest, ~$0.10/q)",
}


def get_api_key() -> str | None:
    """Pull API key from Streamlit secrets or env var."""
    try:
        if "ANTHROPIC_API_KEY" in st.secrets:
            return st.secrets["ANTHROPIC_API_KEY"]
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


def is_configured() -> bool:
    return bool(get_api_key())


def _client():
    """Return an anthropic.Anthropic client. Raises if not configured."""
    key = get_api_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Add to .streamlit/secrets.toml.")
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError("anthropic package not installed. Run: pip install anthropic")
    return Anthropic(api_key=key)


def ask_claude_stream(
    messages: list[dict],
    system: str = "",
    model: str = DEFAULT_MODEL,
    search: bool = True,
    max_tokens: int = 2048,
    search_max_uses: int = 3,
) -> Iterator[dict]:
    """Stream a response from Claude. Yields dicts with type+content.

    Yield shapes:
      {"type": "text", "content": "..."}     # token chunk
      {"type": "tool_use", "name": "web_search", "input": {...}}  # search query
      {"type": "tool_result", "results": [...]}  # web search results
      {"type": "done", "usage": {...}, "sources": [{title, url, ...}, ...]}
      {"type": "error", "message": "..."}
    """
    try:
        client = _client()
    except Exception as e:
        yield {"type": "error", "message": str(e)}
        return

    tools = []
    if search:
        tools.append({
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": search_max_uses,
        })

    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
    )
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    sources: list[dict] = []
    final_usage = None
    try:
        with client.messages.stream(**kwargs) as stream:
            for event in stream:
                event_type = getattr(event, "type", None)
                if event_type == "content_block_start":
                    block = getattr(event, "content_block", None)
                    if block and getattr(block, "type", None) == "tool_use":
                        yield {
                            "type": "tool_use",
                            "name": getattr(block, "name", "?"),
                            "input": getattr(block, "input", {}) or {},
                        }
                elif event_type == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    if delta and getattr(delta, "type", None) == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            yield {"type": "text", "content": text}
                elif event_type == "message_stop":
                    pass
            final_message = stream.get_final_message()
            final_usage = getattr(final_message, "usage", None)
            # Pull citations / sources from any content blocks
            for block in getattr(final_message, "content", []):
                if getattr(block, "type", None) == "web_search_tool_result":
                    content = getattr(block, "content", []) or []
                    for r in content:
                        sources.append({
                            "title": getattr(r, "title", ""),
                            "url": getattr(r, "url", ""),
                            "snippet": (getattr(r, "encrypted_content", "") or "")[:200],
                        })
                # Also check text blocks for inline citations
                if getattr(block, "type", None) == "text":
                    citations = getattr(block, "citations", None) or []
                    for c in citations:
                        sources.append({
                            "title": getattr(c, "title", ""),
                            "url": getattr(c, "url", ""),
                            "snippet": getattr(c, "cited_text", "")[:200],
                        })
        usage_dict = {}
        if final_usage:
            usage_dict = {
                "input_tokens": getattr(final_usage, "input_tokens", 0),
                "output_tokens": getattr(final_usage, "output_tokens", 0),
            }
        yield {"type": "done", "usage": usage_dict, "sources": sources}
    except Exception as e:
        yield {"type": "error", "message": f"API error: {e}"}


def ask_claude(messages: list[dict], **kwargs) -> dict:
    """Non-streaming wrapper. Returns {text, sources, usage, error}."""
    full_text = ""
    sources = []
    usage = {}
    error = None
    tool_uses = []
    for ev in ask_claude_stream(messages, **kwargs):
        if ev["type"] == "text":
            full_text += ev["content"]
        elif ev["type"] == "tool_use":
            tool_uses.append(ev)
        elif ev["type"] == "done":
            sources = ev["sources"]
            usage = ev["usage"]
        elif ev["type"] == "error":
            error = ev["message"]
    return {
        "text": full_text,
        "sources": sources,
        "tool_uses": tool_uses,
        "usage": usage,
        "error": error,
    }


def build_market_context() -> str:
    """Return a markdown block summarizing current market state for context.

    Pulls live indices + macro regime. Cached so calls don't hammer FRED/yfinance.
    """
    from lib import indices, data, indicators
    lines = ["**Today's market snapshot:**\n"]

    # Major indices
    snaps = indices.all_snapshots(categories=["equity", "volatility", "rates"])
    for s in snaps[:6]:
        if s.get("error"):
            continue
        level = indices.fmt_index_level(s["symbol"], s["level"], s["fmt_hint"])
        day = s.get("day_pct")
        ytd = s.get("ytd_pct")
        line = f"- {s['name']} ({s['symbol']}): {level}"
        if day is not None:
            line += f", today {day*100:+.2f}%"
        if ytd is not None:
            line += f", YTD {ytd*100:+.1f}%"
        lines.append(line)

    # Macro regime quick read
    lines.append("\n**Macro regime:**")
    for tile in indicators.REGIME_TILES[:5]:
        series = data.get_fred_series(tile["fred_id"])
        if series and "value" in series:
            v = series["value"]
            lines.append(f"- {tile['label']}: {v:.2f} ({series.get('trend','?')})")

    return "\n".join(lines)


def build_system_prompt(page: str, context_extra: str = "") -> str:
    """Construct a system prompt for a given page context."""
    base = (
        "You are an expert investment research assistant inside an app called Stock Analysis. "
        "Be honest, specific, and concise. Avoid hedging. When the user asks 'why' questions about "
        "stocks or sectors, USE web search to find recent news, earnings, and analyst commentary. "
        "Always cite specific data points. When you cite numbers, say where they came from.\n\n"
        "Format: short paragraphs, bullets when listing multiple items, no em-dashes (user preference). "
        "When relevant, end with one or two concrete next steps the user could take.\n\n"
        f"Current page: {page}\n\n"
    )
    market = build_market_context()
    base += market
    if context_extra:
        base += "\n\n" + context_extra
    return base
