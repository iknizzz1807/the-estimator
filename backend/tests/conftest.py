"""Test bootstrap: force the offline stub provider regardless of a local .env.

A developer .env may set LLM_PROVIDER=deepseek with a real API key. Real
environment variables take precedence over .env in pydantic-settings, so
setting the variable here keeps the whole test suite offline, deterministic
and free. (Tests that exercise the DeepSeek factory override the env via
monkeypatch explicitly.)
"""

import os

os.environ["LLM_PROVIDER"] = "stub"
