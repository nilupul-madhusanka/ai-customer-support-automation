import argparse

from services.ai_service import analyze_inquiry, analyze_offline, require_gemini_config
from services.storage import get_repository
from services.ticket_service import process_new, retry_ticket


def main() -> int:
    parser = argparse.ArgumentParser(description="Draft support replies for human review. No messages are sent.")
    parser.add_argument("--demo", action="store_true", help="Use offline fixtures and a separate demo CSV; no AI calls")
    parser.add_argument("--limit", type=int, default=6, help="Maximum new tickets per batch (1–100)")
    parser.add_argument("--retry", metavar="TICKET_ID", help="Reset one ERROR ticket to NEW, without processing it")
    args = parser.parse_args()
    try:
        repository = get_repository(offline=args.demo)
        if args.retry:
            retry_ticket(repository, args.retry)
            print(f"Reset {args.retry} to NEW. Run the processor to retry.")
            return 0
        if not args.demo and any(t["status"] == "NEW" for t in repository.load()):
            require_gemini_config()
        if args.demo:
            print("OFFLINE DEMO: deterministic fixtures, not Gemini AI. Separate demo CSV.")
        result = process_new(repository, analyze_offline if args.demo else analyze_inquiry,
                             limit=args.limit, report=print)
        print(f"Drafted: {result.succeeded}; errors: {result.failed}; skipped/deferred: {result.skipped}")
        return 1 if result.failed else 0
    except Exception as exc:
        from services.config import ConfigurationError
        print(str(exc) if isinstance(exc, ConfigurationError) else f"Processing stopped ({type(exc).__name__}); check the source file, configuration, and permissions.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
