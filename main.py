import argparse

from services.ai_service import analyze_inquiry, require_gemini_config
from services.storage import get_repository
from services.ticket_service import process_new, retry_ticket
from services.errors import public_error


def main() -> int:
    parser = argparse.ArgumentParser(description="Draft support replies for human review. No messages are sent.")
    parser.add_argument("--limit", type=int, default=6, help="Maximum new tickets per batch (1–100)")
    parser.add_argument("--retry", metavar="TICKET_ID", help="Reset one ERROR ticket to NEW, without processing it")
    args = parser.parse_args()
    try:
        repository = get_repository()
        if args.retry:
            retry_ticket(repository, args.retry)
            print(f"Reset {args.retry} to NEW. Run the processor to retry.")
            return 0
        if any(t["status"] == "NEW" for t in repository.load()):
            require_gemini_config()
        result = process_new(repository, lambda message: analyze_inquiry(message, report=print),
                             limit=args.limit, report=print)
        print(f"Drafted: {result.succeeded}; errors: {result.failed}; skipped/deferred: {result.skipped}")
        if result.stopped_reason:
            print(result.stopped_reason)
        return 1 if result.failed or result.stopped_reason else 0
    except Exception as exc:
        print(public_error(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
