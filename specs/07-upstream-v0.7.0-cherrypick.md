# SPEC: Cherry-pick from Upstream v0.7.0

## Summary
Upstream v0.7.0 has valuable features we should adopt while keeping our superior fallback chain implementation.

## What to Cherry-pick

### 1. ChatGPT Provider (HIGH VALUE)
**File:** `tradingagents/llm_clients/chatgpt_auth.py` (NEW) + `openai_client.py` changes

- **OAuth flow** for "Sign in with ChatGPT" - uses user's ChatGPT Plus/Pro plan
- No API key needed - authenticates via PKCE + dynamic client registration
- Tokens auto-refreshed under lock (1-hour expiry)
- Runs on OpenAI's Responses API
- Refuses sampling/length settings (`temperature`, `top_p`, `max_tokens`)

**Why valuable:** Users with ChatGPT Plus/Pro can run without API keys.

### 2. Per-Tier Provider API (HIGH VALUE)
**File:** `tradingagents/llm_clients/factory.py` - `tier_provider()`, `create_tier_client()`

Cleaner API than our config-based approach:
```python
def tier_provider(config: dict, tier: str) -> str:
    """The provider of the 'quick' or 'deep' model tier."""
    return (config.get(f"{tier}_think_provider") or config["llm_provider"]).lower()

def create_tier_client(config: dict, tier: str, **extra) -> BaseLLMClient:
    """The client for the 'quick' or 'deep' model tier."""
    provider = tier_provider(config, tier)
    # Handles base_url logic correctly per tier
    ...
```

**Why valuable:** Cleaner than our `_tier_llm_settings()` + manual config merging.

### 3. ChatGPT Auth Module (NEW)
**File:** `tradingagents/llm_clients/chatgpt_auth.py` (NEW, ~400 lines)

Complete OAuth implementation:
- Dynamic client registration
- PKCE + loopback redirect on 127.0.0.1
- Token storage in `~/.tradingagents/chatgpt_cred.json` (owner-readable only)
- Auto-refresh under lock (rotating refresh tokens)

### 4. Capability Fixes (MEDIUM VALUE)
**File:** `tradingagents/llm_clients/capabilities.py`

- `deepseek-flash` pattern added for thinking-mode quirks
- Removed `_ANTHROPIC_NO_FORCED_TOOL` (Claude 5.x now supports tool_choice?)
- Pattern updates for deepseek-flash variants

### 5. ChatGPT Plan Provider (NEW)
**File:** `tradingagents/llm_clients/openai_client.py` - `ChatGPTPlanChatOpenAI`

- Subclass of `NormalizedChatOpenAI`
- Uses Responses API (`use_responses_api=True`)
- Refuses `temperature`, `top_p`, `max_tokens` with warning
- No stored responses, no system role (uses `developer` role)
- No org/project sent with plan credentials

## What NOT to Cherry-pick (We Have Better)

| Upstream v0.7.0 | Our Fork (Better) |
|-----------------|-------------------|
| No fallback chains | ✅ Cross-provider fallback chains |
| No OpenRouter native fallback | ✅ OpenRouter `models` array (capped at 3) |
| No client-side fallback | ✅ Client-side sequential fallback for ALL providers |
| Removed connection retry | ✅ Connection retry logic for relays |
| Removed wire protocol config | ✅ `llm_wire_protocol` support |
| Removed timeout coercion | ✅ Timeout validation + bounds |

## Cherry-pick Order

1. **Add ChatGPT auth module** (new file)
2. **Add ChatGPT provider** to `openai_client.py` + `ProviderSpec`
3. **Add `tier_provider` / `create_tier_client`** to `factory.py`
4. **Update `build_llm_kwargs`** - keep our timeout/wire_protocol, add `REASONING_EFFORT_PROVIDERS`
5. **Update capability patterns** in `capabilities.py`
6. **Update `__init__.py` exports** - add `create_tier_client`, `tier_provider`
7. **Add `chatgpt` to api_key_env.py** (key = None)

## Files to Modify

| File | Action |
|------|--------|
| `tradingagents/llm_clients/chatgpt_auth.py` | **CREATE** - new OAuth module |
| `tradingagents/llm_clients/openai_client.py` | **MODIFY** - add ChatGPTPlanChatOpenAI, ProviderSpec for chatgpt |
| `tradingagents/llm_clients/factory.py` | **MODIFY** - add `tier_provider`, `create_tier_client`, simplify `build_llm_kwargs` |
| `tradingagents/llm_clients/capabilities.py` | **MODIFY** - deepseek patterns, remove anthropic no-tool |
| `tradingagents/llm_clients/api_key_env.py` | **MODIFY** - add chatgpt: None |
| `tradingagents/llm_clients/__init__.py` | **MODIFY** - export `create_tier_client`, `tier_provider` |
| `tradingagents/default_config.py` | **MODIFY** - add `quick_think_provider`, `deep_think_provider` env overrides |

## What to Preserve (DO NOT REMOVE)

```python
# In openai_client.py - KEEP THESE:
- _CONNECTION_RETRIES, _CONNECTION_RETRY_WAIT
- _IncompleteStreamError, _is_connection_error, _is_retryable_stream_error
- LocalCompatibleChatOpenAI._stream / _astream (connection retry logic)
- OpenRouter native fallback (models array, capped at 3)
- llm_wire_protocol handling (chat/responses)
- llm_timeout coercion and bounds

# In factory.py - KEEP:
- build_llm_kwargs timeout/wire_protocol/per-tier logic
- _coerce_timeout, _coerce_max_tokens

# In all clients - KEEP fallback chains:
- fallback_model_names handling
- create_fallback_chain() calls
```

## Testing

```bash
# After cherry-pick:
.venv/bin/python -m pytest tests/test_openrouter_fallbacks.py -v
.venv/bin/python -m pytest tests/test_provider_registry.py -v
.venv/bin/python -m pytest tests/ -q
```

## Verification

```bash
# Test ChatGPT provider (requires sign-in)
TRADINGAGENTS_QUICK_PROVIDER=chatgpt \
TRADINGAGENTS_QUICK_THINK_LLM=gpt-4o \
python -c "from tradingagents.llm_clients.factory import create_llm_client; c=create_llm_client('chatgpt', 'gpt-4o'); print(c.get_llm())"

# Test per-tier provider
config = DEFAULT_CONFIG.copy()
config["quick_think_provider"] = "anthropic"
config["deep_think_provider"] = "openrouter"
from tradingagents.llm_clients.factory import create_tier_client
quick = create_tier_client(config, "quick")
deep = create_tier_client(config, "deep")
```