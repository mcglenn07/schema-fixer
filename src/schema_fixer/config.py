"""Explicit provider configuration; never include keys in reports or reprs."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from schema_fixer.providers import ProviderError

DEFAULT_MODEL = "gpt-6-luna"


@dataclass(frozen=True)
class Settings:
    provider: str = "openai"
    model: str = DEFAULT_MODEL
    api_key: str | None = field(default=None, repr=False)


def load_settings(provider: str | None = None) -> Settings:
    # Do not search ancestor directories or interpolate secrets into other settings.
    path = Path.cwd() / ".env"
    try:
        values = dotenv_values(path, interpolate=False) if path.is_file() else {}
    except (OSError, UnicodeError) as exc:
        raise ProviderError("Cannot read the local .env file.") from exc

    def setting(name: str, default=None):
        return os.environ.get(name, values.get(name) or default)

    selected = (
        provider if provider is not None else setting("PROVIDER", "openai")
    ).strip()
    if selected not in {"baseline", "openai"}:
        raise ProviderError(
            "M2 supports baseline and openai. Ollama is a later milestone."
        )
    if selected == "baseline":
        return Settings(provider="baseline")
    model = setting("OPENAI_MODEL", DEFAULT_MODEL).strip()
    if not model:
        raise ProviderError("OPENAI_MODEL must not be empty.")
    return Settings(provider=selected, model=model, api_key=setting("OPENAI_API_KEY"))
