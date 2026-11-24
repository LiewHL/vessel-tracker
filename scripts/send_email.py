import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mailer import send


def main():
    args = sys.argv[1:]
    to = None
    if "--to" in args:
        i = args.index("--to")
        to = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    summary_path, report_path, subject, dash_url, _unused = args[0:5]
    extras = [p for p in args[5:] if p and os.path.isfile(p)]
    with open(summary_path, encoding="utf-8") as f:
        summary = f.read().strip()
    body = (f"{summary}\n\nDashboard (passcode needed): {dash_url}\n"
            "No copy of this report is kept on the dashboard or elsewhere, so please save this email "
            "(or the attachments) if you need them later.\n\n"
            "Attached: the full report (open in a browser; Print > Save as PDF for a PDF copy; "
            "press Export in the report for an Excel copy of its tables)"
            + (" and the data workbook for Excel (" + ", ".join(os.path.basename(p) for p in extras)
               + ")" if extras else "")
            + ".\n")
    files = []
    with open(report_path, "rb") as f:
        files.append((f.read(), "text", "html", os.path.basename(report_path)))
    for path in extras:
        with open(path, "rb") as f:
            if path.endswith(".xlsx"):
                files.append((f.read(), "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              os.path.basename(path)))
            else:
                files.append((f.read(), "text", "csv", os.path.basename(path)))
    return send(subject, body, files, send_to=to)


if __name__ == "__main__":
    sys.exit(main())
