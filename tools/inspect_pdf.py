"""
Show what the parser sees in a statement PDF, and where it gives up.

Run this on a statement that came back with "ไม่สามารถแยกวิเคราะห์ธุรกรรมจาก PDF
ที่ให้มา". That message means text came out of the PDF fine but no line in it
looked like a transaction, so the answer is always visible in the extracted
text -- this prints it next to what the parser was looking for.

    .venv/bin/python tools/inspect_pdf.py ~/Downloads/statement.pdf
    .venv/bin/python tools/inspect_pdf.py statement.pdf --all   # every line
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.parser.pdf_extractor import PDFExtractionError, PDFTextExtractor  # noqa: E402
from src.parser.record_parser import RecordParser  # noqa: E402

PREVIEW_LINES = 40


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    show_all = "--all" in sys.argv

    if not args:
        print(__doc__)
        return 2

    path = Path(args[0]).expanduser()
    if not path.exists():
        print(f"no such file: {path}")
        return 2

    print(f"file      {path}")
    print(f"size      {path.stat().st_size:,} bytes")

    try:
        text = PDFTextExtractor().extract_text_from_pdf_bytes(path.read_bytes())
    except PDFExtractionError as e:
        print(f"\nEXTRACTION FAILED: {e}")
        print(
            "\nThe PDF gave up no text at all. It is most likely a scan (an image of a\n"
            "statement rather than a statement), or password protected. Neither can be\n"
            "parsed without OCR or the password."
        )
        return 1

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    print(f"text      {len(text):,} chars, {len(lines)} non-empty lines")

    parser = RecordParser()
    matched = [ln for ln in lines if parser.DATE_PATTERN.match(ln)]

    print(f"\nlines starting with a DD-MM-YY date: {len(matched)}")
    print("   (this is what the parser uses to find the start of a transaction,")
    print(f"    pattern {parser.DATE_PATTERN.pattern!r})")

    transactions = parser.parse_statement_text(text, date.today().replace(day=1))
    stats = parser.stats

    print(
        f"\nparsed    {len(transactions)} transactions "
        f"(attempted {stats.attempted}, opening-balance rows {stats.opening_balance}, "
        f"failed {stats.failed})"
    )

    if matched and not transactions:
        print(
            "\nDIAGNOSIS: the dates are being found but the rest of each line is not.\n"
            "The layout differs from what the parser expects after the date -- a\n"
            "different column order, different wording, or amounts and balances that\n"
            "are not where it looks for them."
        )
    elif not matched:
        print(
            "\nDIAGNOSIS: no line in this PDF starts with a DD-MM-YY date.\n"
            "Either the dates are written in another format (DD/MM/YYYY, a Thai month\n"
            "name, a four-digit year), or the columns come out of the PDF in an order\n"
            "that does not put the date first."
        )
    else:
        print("\nThis statement parses. If the app still refused it, the problem is elsewhere.")

    print("\n" + "=" * 78)
    print("WHAT THE PARSER WANTS (a line it can read):")
    print("=" * 78)
    print("05-01-26 09:00 ชำระเงิน 399.00 19,601.00 K PLUS เพื่อชำระ Ref X1001 NETFLIX")
    print(" └date─┘ └time┘ └─type──┘ └amt─┘ └balance┘ └channel┘         └──detail──┘")
    print("\ntypes it knows: ชำระเงิน · โอนเงิน · รับโอนเงิน · ยอดยกมา")

    print("\n" + "=" * 78)
    print(f"WHAT YOUR PDF ACTUALLY CONTAINS ({'all' if show_all else f'first {PREVIEW_LINES}'} lines):")
    print("=" * 78)

    for i, line in enumerate(lines if show_all else lines[:PREVIEW_LINES], start=1):
        mark = "OK " if parser.DATE_PATTERN.match(line) else "   "
        print(f"{mark}{i:4} | {line[:150]}")

    if not show_all and len(lines) > PREVIEW_LINES:
        print(f"\n... {len(lines) - PREVIEW_LINES} more lines. Pass --all to see them.")

    print("\nLines marked OK are ones the parser recognises as starting a transaction.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
