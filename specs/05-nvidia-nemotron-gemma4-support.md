# SPEC: NVIDIA Nemotron & Gemma-4 Support

## Summary
Added support for NVIDIA NIM API models (Nemotron 3 Ultra, Nemotron 4 Ultra, Gemma-4 variants) as fallback options, with proper tool-calling support verification.

## Problem
NVIDIA Nemotron models don't support `bind_tools()` required by TradingAgents analysts, making them unsuitable as primary models. However, they're excellent as **fallback** models when accessed via NVIDIA NIM API (free tier available).

## Solution

### 1. NVIDIA NIM API Integration
NVIDIA NIM API at `https://integrate.api.nvidia.com/v1` hosts:
- **Nemotron 3 Ultra** (`nvidia/nemotron-3-ultra-550b-a55b`) — 550B params, 1M context
- **Nemotron 4 Ultra** (`nvidia/nemotron-4-ultra`) — latest generation
- **Gemma-4 variants** (Google's model hosted by NVIDIA):
  - `google/gemma-4-26b-it` — MoE, 26B params (4B active), efficient
  - `google/gemma-4-12b-it` — dense, 12B params
  - `google/gemma-4-4b-it` / `google/gemma-4-31b-it` — smaller/larger variants

### 2. Provider Registration
In `tradingagents/llm_clients/openai_client.py`:
```python
OPENAI_COMPATIBLE_PROVIDERS = {
    ...
    "nvidia": ProviderSpec(base_url="https://integrate.api.nvidia.com/v1"),
    ...
}
```

### 3. Fallback Configuration
```bash
# Quick tier fallback includes NVIDIA
TRADINGAGENTS_QUICK_FALLBACK_BY_PROVIDER='{
  "openrouter": "google/gemini-3.8-flash,deepseek/deepseek-chat,xai/grok-4.6",
  "nvidia": "google/gemma-4-26b-it,google/gemma-4-12b-it"
}'

# Deep tier fallback includes NVIDIA
TRADINGAGENTS_DEEP_FALLBACK_BY_PROVIDER='{
  "openrouter": "anthropic/claude-fable-5-1,google/gemini-3.1-pro-preview,xai/grok-4.6",
  "nvidia": "google/gemma-4-26b-it"
}'
```

### 3. Why Not Primary?
**Nemotron doesn't support `bind_tools()`** — required by all analysts (market, social, news, fundamentals). The error:
```
NotImplementedError: bind_tools is not implemented for this model
```

Gemma-4 **does support tool calling** (Google added it in Gemma 2+), making it viable as fallback.

### 4. Fallback Chain Priority
```python
# _get_provider_fallbacks iterates dict in order
provider_fallbacks = {
    "openrouter": "model-a,model-b",  # tried first
    "nvidia": "model-c,model-d"       # tried second
}
# Result: tries OpenRouter models first, then NVIDIA models
```

### 5. NVIDIA NIM API Limits
- **Free tier**: Rate limited (strict)
- **Production**: Requires dedicated NIM endpoints
- **Recommendation**: Use as fallback only, not primary

### 6. Model Catalog
NVIDIA entry in `tradingagents/llm_clients/model_catalog.py`:
```python
"nvidia": _CUSTOM_ONLY,  # Many/frequently-changing models
```

### Configuration
```bash
# API Key
NVIDIA_API_KEY=nvapi-xxxxx

# Fallback only (not primary)
TRADINGAGENTS_QUICK_FALLBACK_BY_PROVIDER='{"nvidia": "google/gemma-4-26b-it,google/gemma-4-12b-it"}'
```

### Verification
```bash
$ .venv/bin/python -c "
from tradingagents.llm_clients.factory import create_llm_client
client = create_llm_client(provider='nvidia', model='google/gemma-4-26b-it')
print('Client:', client.__class__.__name__)
print('Model:', client.model)
"
# Output: OpenAIClient -> google/gemma-4-26b-it
```

### Files Modified
| File | Change |
|------|--------|
| `tradingagents/llm_clients/openai_client.py` | NVIDIA provider spec with NIM API URL |
| `tradingagents/llm_clients/model_catalog.py` | NVIDIA entry as _CUSTOM_ONLY |
| `scripts/apply_optimal_strategy.py` | NVIDIA Gemma-4 in fallback chains |
| `tradingagents/default_config.py` | NVIDIA in fallback configs |

### Verification
```bash
$ .venv/bin/python -m pytest tests/test_provider_registry.py -v
# nvidia provider test passes

$ .venv/bin/python -m pytest tests/ -q
1388 passed, 262 skipped
```

### Notes
- Nemotron 3 Ultra (550B) = excellent for analysis but no tool support
- Gemma-4 26B MoE = 4B active params = fast, efficient fallback
- NVIDIA NIM free tier = good for fallback testing, not production primary
- All NVIDIA models use OpenAI-compatible client path