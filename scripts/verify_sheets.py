"""Check Google Sheets access without modifying tickets or calling Gemini.

Run from the project root: python -m scripts.verify_sheets
"""
from services.storage import get_repository
from services.errors import public_error


def main():
    rows = get_repository().load()
    print(f"Google Sheets access verified: {len(rows)} valid inquiries.")
    print(f"New inquiries awaiting processing: {sum(row['status'] == 'NEW' for row in rows)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(public_error(exc))
        raise SystemExit(1)
