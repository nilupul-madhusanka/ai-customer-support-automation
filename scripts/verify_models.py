"""Read Gemini model metadata only; never generate replies or read inquiries."""
import os

from services.ai_service import model_policy, require_gemini_config
from services.errors import public_error
from services.model_discovery import discover_models


def main():
    from google import genai
    from google.genai import types
    require_gemini_config()
    policy = model_policy()
    with genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(
        timeout=5000, retry_options=types.HttpRetryOptions(attempts=1),
    )) as client:
        discovered = discover_models(client, os.environ["GEMINI_API_KEY"], timeout_ms=5000)
    candidates = tuple(dict.fromkeys([*policy.models, *discovered]))
    print(f"Discovered {len(discovered)} general-purpose Gemini text candidates.")
    print(f"Automatic discovery: {policy.auto_discover}; generation attempts: {policy.max_attempts}; budget: {policy.seconds}s.")
    print("Next candidate order: " + ", ".join(candidates[:policy.max_attempts]))
    print("Catalog membership does not guarantee current capacity or JSON Schema compatibility. No replies were generated.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(public_error(exc))
        raise SystemExit(1)
