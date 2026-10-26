#!/usr/bin/env python3
"""Apply optimal LLM strategy to .env and verify it loads correctly."""

import shutil
import sys
from pathlib import Path

ENV_PATH = Path("/Users/mac/Code/tradingagents/.env")
BACKUP_PATH = Path("/Users/mac/Code/tradingagents/.env.backup")

# Optimal strategy configuration
OPTIMAL_CONFIG = {
    # Quick tier: OpenRouter + Anthropic Sonnet 5 (fast, cheap, tool-capable)
    # NVIDIA Nemotron doesn't support bind_tools() required by analysts
    "TRADINGAGENTS_QUICK_PROVIDER": "openrouter",
    "TRADINGAGENTS_QUICK_THINK_LLM": "anthropic/claude-sonnet-5",

    # Quick fallback: OpenRouter + NVIDIA (cross-provider redundancy)
    "TRADINGAGENTS_QUICK_FALLBACK_BY_PROVIDER": '{"openrouter": "google/gemini-3.8-flash,deepseek/deepseek-chat,xai/grok-4.6", "nvidia": "google/gemma-4-26b-it,google/gemma-4-12b-it"}',

    # Deep tier: OpenRouter + Anthropic Opus 5.5 (best reasoning)
    "TRADINGAGENTS_DEEP_PROVIDER": "openrouter",
    "TRADINGAGENTS_DEEP_THINK_LLM": "anthropic/claude-opus-5-5",

    # Deep fallback: OpenRouter + NVIDIA (cross-provider redundancy)
    "TRADINGAGENTS_DEEP_FALLBACK_BY_PROVIDER": '{"openrouter": "anthropic/claude-fable-5-1,google/gemini-3.1-pro-preview,xai/grok-4.6", "nvidia": "google/gemma-4-26b-it"}',

    # Lower temperature for more deterministic runs
    "TRADINGAGENTS_TEMPERATURE": "0.1",

    # Disable legacy single-provider fallback (replaced by provider-specific)
    "TRADINGAGENTS_QUICK_FALLBACK_MODELS": "",
    "TRADINGAGENTS_DEEP_FALLBACK_MODELS": "",
}

def read_env(path: Path) -> dict:
    """Read .env file into dict, preserving comments and order."""
    if not path.exists():
        return {}
    result = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if "=" in line and not line.strip().startswith("#"):
                key, val = line.split("=", 1)
                result[key.strip()] = val.strip()
    return result

def write_env(path: Path, env: dict, original_lines: list[str] = None):
    """Write .env file, updating existing keys and appending new ones."""
    updated_keys = set()
    lines = []

    if original_lines:
        for line in original_lines:
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=")[0].strip()
                if key in env:
                    lines.append(f"{key}={env[key]}")
                    updated_keys.add(key)
                    continue
            lines.append(line.rstrip("\n"))

    # Add new keys not in original
    for key, val in env.items():
        if key not in updated_keys:
            lines.append(f"{key}={val}")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

def verify_config():
    """Verify the config loads and clients can be created."""
    # Force reload of config
    if "tradingagents.default_config" in sys.modules:
        del sys.modules["tradingagents.default_config"]
    if "tradingagents.llm_clients.factory" in sys.modules:
        del sys.modules["tradingagents.llm_clients.factory"]
    if "tradingagents.graph.trading_graph" in sys.modules:
        del sys.modules["tradingagents.graph.trading_graph"]

    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.llm_clients.factory import create_llm_client

    print("\n=== Config Verification ===")
    print(f"quick_provider:       {DEFAULT_CONFIG.get('quick_provider')}")
    print(f"quick_think_llm:      {DEFAULT_CONFIG.get('quick_think_llm')}")
    print(f"quick_fallback_by_provider: {DEFAULT_CONFIG.get('quick_fallback_by_provider')}")
    print(f"deep_provider:        {DEFAULT_CONFIG.get('deep_provider')}")
    print(f"deep_think_llm:       {DEFAULT_CONFIG.get('deep_think_llm')}")
    print(f"deep_fallback_by_provider: {DEFAULT_CONFIG.get('deep_fallback_by_provider')}")
    print(f"temperature:          {DEFAULT_CONFIG.get('temperature')}")

    # Test client creation (no API call, just config)
    print("\n=== Client Creation Test ===")
    try:
        quick_client = create_llm_client(
            provider=DEFAULT_CONFIG["quick_provider"],
            model=DEFAULT_CONFIG["quick_think_llm"],
        )
        print(f"Quick client: {quick_client.__class__.__name__} -> model={quick_client.model}")
    except Exception as e:
        print(f"Quick client FAILED: {e}")
        return False

    try:
        deep_client = create_llm_client(
            provider=DEFAULT_CONFIG["deep_provider"],
            model=DEFAULT_CONFIG["deep_think_llm"],
        )
        print(f"Deep client:  {deep_client.__class__.__name__} -> model={deep_client.model}")
    except Exception as e:
        print(f"Deep client FAILED: {e}")
        return False

    # Test fallback chain resolution
    from tradingagents.graph.trading_graph import _fallback_models
    quick_fallbacks = _fallback_models(DEFAULT_CONFIG, "quick", DEFAULT_CONFIG["quick_provider"])
    deep_fallbacks = _fallback_models(DEFAULT_CONFIG, "deep", DEFAULT_CONFIG["deep_provider"])
    print(f"\nQuick fallbacks: {quick_fallbacks}")
    print(f"Deep fallbacks:  {deep_fallbacks}")

    print("\n✅ All checks passed!")
    return True

def main():
    print(f"Reading {ENV_PATH}...")
    original_content = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    original_lines = original_content.splitlines()

    # Backup
    shutil.copy2(ENV_PATH, BACKUP_PATH)
    print(f"Backed up to {BACKUP_PATH}")

    # Read current env
    current_env = read_env(ENV_PATH)

    # Apply optimal config
    print("\nApplying optimal strategy...")
    for key, val in OPTIMAL_CONFIG.items():
        old = current_env.get(key, "(not set)")
        current_env[key] = val
        print(f"  {key}: {old} -> {val}")

    # Write updated .env
    write_env(ENV_PATH, current_env, original_lines)
    print(f"\nUpdated {ENV_PATH}")

    # Verify
    print("\nVerifying configuration...")
    if verify_config():
        print("\n🎉 Optimal strategy applied successfully!")
        print("\nNext steps:")
        print("  1. Ensure OPENROUTER_API_KEY is set (already in your .env)")
        print("  2. Run: tradingagents --help  # verify CLI works")
        print("  3. Run a test: python -c \"from tradingagents.main import ta; print('OK')\"")
        return 0
    else:
        print("\n❌ Verification failed. Restoring backup...")
        shutil.copy2(BACKUP_PATH, ENV_PATH)
        return 1

if __name__ == "__main__":
    sys.exit(main())
