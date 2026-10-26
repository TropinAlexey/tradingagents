"""Parallel execution of analysts for faster cycle times."""

import asyncio
from typing import Any

from tradingagents.agents.analysts.fundamentals_analyst import create_fundamentals_analyst
from tradingagents.agents.analysts.market_analyst import create_market_analyst
from tradingagents.agents.analysts.news_analyst import create_news_analyst
from tradingagents.agents.analysts.sentiment_analyst import create_sentiment_analyst

# Analyst node names for state keys
ANALYST_REPORT_KEYS = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}

ANALYST_NODE_NAMES = {
    "market": "Market Analyst",
    "social": "Sentiment Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}

ANALYST_CREATORS = {
    "market": create_market_analyst,
    "social": create_sentiment_analyst,
    "news": create_news_analyst,
    "fundamentals": create_fundamentals_analyst,
}


async def _run_analyst(analyst_key: str, llm: Any, state: dict) -> dict[str, Any]:
    """Run a single analyst and return its report."""
    creator = ANALYST_CREATORS[analyst_key]
    # The creator returns a node function that takes a state dict
    # Pass the LLM directly to the creator
    analyst_node = creator(llm)

    # The analyst node function expects a state dict
    result = await _invoke_analyst(analyst_node, state)
    # The analyst node returns a dict with the report key (e.g., "market_report")
    report_key = f"{analyst_key}_report" if analyst_key != "social" else "sentiment_report"
    if analyst_key == "social":
        report_key = "sentiment_report"
    elif analyst_key == "market":
        report_key = "market_report"
    elif analyst_key == "news":
        report_key = "news_report"
    elif analyst_key == "fundamentals":
        report_key = "fundamentals_report"

    return {report_key: result.get(report_key, "")}


async def _invoke_analyst(analyst_node, state: dict):
    """Invoke analyst node, handling both sync and async."""
    import inspect
    if inspect.iscoroutinefunction(analyst_node):
        return await analyst_node(state)
    else:
        # Run sync function in thread pool to avoid blocking
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, analyst_node, state)


async def run_analysts_parallel(state: dict, llm) -> dict[str, Any]:
    """Run all selected analysts in parallel and return combined state updates.

    This replaces the sequential execution of analysts with parallel execution,
    significantly reducing cycle time.
    """
    selected_analysts = state.get("selected_analysts", ["market", "social", "news", "fundamentals"])

    # Filter to only available analysts
    available_analysts = [k for k in selected_analysts if k in ANALYST_CREATORS]

    # Run all analysts in parallel
    tasks = [_run_analyst(key, llm, state) for key in available_analysts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Combine results
    combined = {}
    for _i, result in enumerate(results):
        if isinstance(result, Exception):
            # Log error but continue
            print(f"Analyst error: {result}")
            continue
        combined.update(result)

    return combined


def run_analysts_parallel_sync(state: dict, llm) -> dict:
    """Synchronous wrapper for run_analysts_parallel."""
    return asyncio.run(run_analysts_parallel(state, llm))
