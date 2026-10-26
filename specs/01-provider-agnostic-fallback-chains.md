# SPEC: Provider-Agnostic LLM Fallback Chains

## Summary
Implemented cross-provider fallback chains for ALL LLM providers (not just OpenRouter), enabling any model from any provider to be used as fallback for any tier.

## Problem
Previously, fallback chains only worked with OpenRouter via its native `models` array API. Other providers had no fallback mechanism.

## Solution
Created a universal fallback system that works for ALL providers:

### Architecture
1. **New Config Keys** (`tradingagents/default_config.py`):
   - `TRADINGAGENTS_QUICK_FALLBACK_BY_PROVIDER` — JSON: `{"provider": "model-a,model-b"}`
   - `TRADINGAGENTS_DEEP_FALLBACK_BY_PROVIDER` — same for deep tier
   - Legacy `*_fallback_models` deprecated (kept for backward compat)

2. **New Module** (`tradingagents/llm_clients/fallback.py`):
   - `FallbackChatModel` — wraps primary + fallback models, retries on retryable errors (429, capacity, unavailable, model_not_found)
   - `create_fallback_chain()` — factory to build chains
   - `_get_provider_fallbacks()` — resolves chain with priority:
     1. Provider-specific override (`*_by_provider` dict, iterates in order)
     2. Tier-level fallback (`*_fallback_models`)

3. **All Clients Updated**:
   - OpenAI-compatible (OpenRouter, NVIDIA, xAI, DeepSeek, Qwen, GLM, MiniMax, Mistral, Groq, Ollama, custom) — native (OpenRouter) + client-side (others)
   - Anthropic — client-side fallback
   - Google — client-side fallback
   - Azure — client-side fallback
   - Bedrock — client-side fallback

4. **Graph Integration** (`tradingagents/graph/trading_graph.py`):
   - `_fallback_models(config, tier, provider)` calls `_get_provider_fallbacks` with provider context
   - Passes `fallback_model_names` to client kwargs

### Fallback Resolution Logic
```python
# _get_provider_fallbacks in fallback.py
provider_fallbacks = {"openrouter": "model-a,model-b", "nvidia": "model-c"}
# Iterates dict values in order, returns first non-empty list
```

### Config Format
```bash
# Per-tier, cross-provider fallbacks
TRADINGAGENTS_QUICK_FALLBACK_BY_PROVIDER='{"openrouter": "google/gemini-3.8-flash,deepseek/deepseek-chat,xai/grok-4.6", "nvidia": "google/gemma-4-26b-it,google/gemma-4-12b-it"}'
TRADINGAGENTS_DEEP_FALLBACK_BY_PROVIDER='{"openrouter": "anthropic/claude-fable-5-1,google/gemini-3.1-pro-preview,xai/grok-4.6", "nvidia": "google/gemma-4-26b-it"}'
```

### OpenRouter Native Fallback (Optimization)
For OpenRouter, uses native `extra_body={"models": [...]}` array (single request, no extra round-trips), capped at 3 models.

### Client-Side Fallback (All Other Providers)
Sequential retry on retryable errors:
- 429 / rate_limit / quota / capacity
- unavailable / overloaded / model_not_found
- does_not_exist / not_supported / deprecated

### Testing
- All existing tests pass (1388 passed)
- New tests in `tests/test_openrouter_fallbacks.py` verify:
  - OpenRouter native fallback sends correct `models` array
  - Fallback chains capped at 3 for OpenRouter
  - Other providers ignore OpenRouter-specific fallback
  - Client-side fallback wrapper works correctly

## Files Changed
| File | Purpose |
|------|---------|
| `tradingagents/default_config.py` | New env overrides + defaults |
| `tradingagents/llm_clients/fallback.py` | **New** — fallback wrapper & resolver |
| `tradingagents/llm_clients/factory.py` | Import `create_fallback_chain` |
| `tradingagents/llm_clients/openai_client.py` | Native OpenRouter + client-side fallback |
| `tradingagents/llm_clients/anthropic_client.py` | Client-side fallback |
| `tradingagents/llm_clients/google_client.py` | Client-side fallback |
| `tradingagents/llm_clients/azure_client.py` | Client-side fallback |
| `tradingagents/llm_clients/bedrock_client.py` | Client-side fallback |
| `tradingagents/llm_clients/__init__.py` | Export new symbols |
| `tradingagents/graph/trading_graph.py` | Pass fallback_model_names with provider context |
| `scripts/apply_optimal_strategy.py` | **New** — apply & verify strategy |

## Configuration Example
```bash
# Quick tier (analysts/trader/risk)
TRADINGAGENTS_QUICK_PROVIDER=openrouter
TRADINGAGENTS_QUICK_THINK_LLM=anthropic/claude-sonnet-5
TRADINGAGENTS_QUICK_FALLBACK_BY_PROVIDER={"openrouter": "google/gemini-3.8-flash,deepseek/deepseek-chat,xai/grok-4.6", "nvidia": "google/gemma-4-26b-it,google/gemma-4-12b-it"}

# Deep tier (managers)
TRADINGAGENTS_DEEP_PROVIDER=openrouter
TRADINGAGENTS_DEEP_THINK_LLM=anthropic/claude-opus-5-5
TRADINGAGENTS_DEEP_FALLBACK_BY_PROVIDER={"openrouter": "anthropic/claude-fable-5-1,google/gemini-3.1-pro-preview,xai/grok-4.6", "nvidia": "google/gemma-4-26b-it"}
```

## Verification
```bash
$ .venv/bin/python -m pytest tests/ -q
1388 passed, 262 skipped

$ .venv/bin/python -m ruff check .
All checks passed!
```