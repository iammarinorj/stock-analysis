"""Floating chat in sidebar — calls Claude with web search for live answers.

Each page calls render_chat(page_id, context_fn) once. The chat:
- Persists per-page history in session_state
- Auto-attaches a system prompt with current market state + page context
- Supports web search (toggleable)
- Supports model toggle (Haiku default, Sonnet for depth)
- Shows sources / citations
- Has quick-question buttons that auto-populate the input
"""
from __future__ import annotations

from typing import Callable

import streamlit as st

from lib import ask


PRESETS_BY_PAGE = {
    "stock_pro": [
        "What's the bull case for {ticker}?",
        "What's the bear case for {ticker}?",
        "Why is {ticker} down recently?",
        "What are the biggest risks to {ticker}'s thesis?",
        "How does {ticker} compare to its top competitors?",
        "What did {ticker} say on its last earnings call?",
    ],
    "discover": [
        "Why are these stocks showing up in this screen?",
        "Which of these has the best near-term catalyst?",
        "What's the macro setup for this style today?",
        "Which sectors does this screen cluster in?",
    ],
    "macro_pro": [
        "What's the regime read on US equities right now?",
        "Why is the VIX where it is today?",
        "What does the yield curve currently signal?",
        "Which sectors benefit from the current macro setup?",
    ],
    "thesis": [
        "Which of my open theses look weakest right now?",
        "What news today could affect my open positions?",
    ],
    "backtest": [
        "How should I interpret these backtest results?",
        "What are the limitations of this kind of backtest?",
    ],
    "default": [
        "What's driving markets today?",
        "Which sectors are leading / lagging right now?",
        "What's the biggest macro risk this week?",
    ],
}


def _history_key(page_id: str) -> str:
    return f"chat_history_{page_id}"


def _settings_key() -> str:
    return "chat_settings"


def _get_history(page_id: str) -> list:
    key = _history_key(page_id)
    if key not in st.session_state:
        st.session_state[key] = []
    return st.session_state[key]


def _get_settings() -> dict:
    key = _settings_key()
    if key not in st.session_state:
        st.session_state[key] = {"model": ask.DEFAULT_MODEL, "search": True}
    return st.session_state[key]


def render_chat(page_id: str, context_fn: Callable[[], str] = None):
    """Render the chat panel in the sidebar.

    Args:
      page_id: identifier for the page (used for history namespacing + presets)
      context_fn: optional callable returning a markdown string of current page state
                  to inject into the system prompt
    """
    with st.sidebar:
        st.divider()
        st.markdown("### 🤖 Ask AI")

        if not ask.is_configured():
            with st.expander("⚙️ Setup required", expanded=False):
                st.warning(
                    "Add your Anthropic API key to enable the AI assistant.\n\n"
                    "1. Get key at console.anthropic.com\n"
                    "2. Create `.streamlit/secrets.toml` in this project\n"
                    "3. Add: `ANTHROPIC_API_KEY = \"sk-ant-...\"`\n"
                    "4. Restart streamlit"
                )
            # Still offer copy-paste fallback
            with st.expander("📋 Copy-paste mode (no key needed)"):
                _render_copy_paste(page_id, context_fn)
            return

        settings = _get_settings()
        with st.expander("⚙️ Settings"):
            settings["model"] = st.selectbox(
                "Model",
                options=list(ask.MODEL_LABELS.keys()),
                format_func=lambda m: ask.MODEL_LABELS.get(m, m),
                index=list(ask.MODEL_LABELS.keys()).index(settings["model"]),
                key=f"chat_model_{page_id}",
            )
            settings["search"] = st.toggle(
                "🌐 Web search",
                value=settings["search"],
                help="Let Claude search the web for current news, earnings, analyst notes.",
                key=f"chat_search_{page_id}",
            )

        # Quick-question presets
        presets = PRESETS_BY_PAGE.get(page_id, PRESETS_BY_PAGE["default"])
        active_ticker = st.session_state.get("active_ticker", "")
        with st.expander("💡 Quick questions"):
            for i, preset in enumerate(presets):
                # Fill {ticker} placeholder if applicable
                if "{ticker}" in preset:
                    if not active_ticker:
                        continue
                    label = preset.format(ticker=active_ticker)
                else:
                    label = preset
                if st.button(label, key=f"preset_{page_id}_{i}", use_container_width=True):
                    st.session_state[f"pending_question_{page_id}"] = label
                    st.rerun()

        # Show history
        history = _get_history(page_id)
        if history:
            with st.expander(f"💬 Conversation ({len(history)} msgs)", expanded=True):
                # Render last 6 messages to keep sidebar tidy
                for msg in history[-6:]:
                    role = msg["role"]
                    icon = "🧑" if role == "user" else "🤖"
                    st.markdown(f"**{icon} {role.title()}**")
                    st.markdown(msg["content"][:1000] + ("..." if len(msg["content"]) > 1000 else ""))
                    if msg.get("sources"):
                        with st.expander(f"📎 {len(msg['sources'])} sources"):
                            for s in msg["sources"][:8]:
                                if s.get("url"):
                                    st.markdown(f"- [{s.get('title', s['url'])[:60]}]({s['url']})")
                    st.write("")
                if st.button("🗑 Clear conversation", key=f"clear_{page_id}", use_container_width=True):
                    st.session_state[_history_key(page_id)] = []
                    st.rerun()

        # Input
        pending_key = f"pending_question_{page_id}"
        pending = st.session_state.pop(pending_key, None)
        question = st.chat_input(
            "Ask about this page...",
            key=f"chat_input_{page_id}",
        ) or pending

        if question:
            _handle_question(page_id, question, context_fn, settings)
            st.rerun()


def _handle_question(page_id: str, question: str, context_fn, settings: dict):
    """Send the question to Claude, append assistant reply to history."""
    history = _get_history(page_id)
    history.append({"role": "user", "content": question})

    # Build system prompt
    context_extra = ""
    if context_fn:
        try:
            context = context_fn()
            context_extra = context if context else ""
        except Exception:
            context_extra = "Context unavailable."

    system = ask.build_system_prompt(page_id, context_extra)

    # Build messages from history (Anthropic format: only user/assistant roles)
    api_messages = [{"role": m["role"], "content": m["content"]} for m in history]

    # Stream + collect
    with st.sidebar:
        with st.spinner("🌐 Searching + thinking..." if settings["search"] else "Thinking..."):
            result = ask.ask_claude(
                api_messages,
                system=system,
                model=settings["model"],
                search=settings["search"],
                max_tokens=2048,
            )

    if result.get("error"):
        history.append({"role": "assistant", "content": f"⚠️ {result['error']}"})
    else:
        history.append({
            "role": "assistant",
            "content": result.get("text", "") or "(no response)",
            "sources": result.get("sources", []),
            "usage": result.get("usage", {}),
        })


def _render_copy_paste(page_id: str, context_fn):
    """Fallback when no API key — show pre-built prompt to copy into Claude.ai."""
    q = st.text_area(
        "Your question",
        placeholder="Why are X companies cheap right now?",
        key=f"cp_q_{page_id}",
        height=80,
    )
    if st.button("Build prompt", key=f"cp_build_{page_id}", use_container_width=True):
        context_extra = ""
        if context_fn:
            try:
                context = context_fn()
                context_extra = context if context else ""
            except Exception:
                context_extra = "Context unavailable."
        full_prompt = (
            f"{ask.build_system_prompt(page_id, context_extra)}\n\n"
            f"---\n\nMy question: {q}"
        )
        st.code(full_prompt, language="markdown")
        st.caption("Copy the text above and paste into claude.ai or any AI chat.")
