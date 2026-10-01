# -*- coding: utf-8 -*-
"""قالبِ داشبورد + دادهٔ تازه = صفحهٔ نهایی.

قالب `app/tomorrow.tmpl.html` است و یک جای‌گیر `__DATA__` دارد داخل
`<script id="D" type="application/json">`. اینجا `data/dash.json` تویش
ریخته می‌شود. جدا نگه‌داشتنِ قالب از داده یعنی اکشنِ گیت‌هاب می‌تواند هر
روز صفحه را بسازد بدون اینکه کسی HTML را دست بزند.
"""
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    root = Path(__file__).resolve().parent.parent
    ap.add_argument("--tmpl", default=str(root / "app/tomorrow.tmpl.html"))
    ap.add_argument("--data", default=str(root / "data/dash.json"))
    ap.add_argument("--out", default=str(root / "app/tomorrow.html"))
    args = ap.parse_args()

    tmpl = Path(args.tmpl).read_text(encoding="utf-8")
    if "__DATA__" not in tmpl:
        raise SystemExit(f"جای‌گیر __DATA__ در {args.tmpl} نیست.")
    data = Path(args.data).read_text(encoding="utf-8")
    json.loads(data)          # اگر JSON خراب باشد همین‌جا می‌ترکد، نه در مرورگر
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(tmpl.replace("__DATA__", data), encoding="utf-8")
    print(f"نوشته شد: {out}  ({out.stat().st_size:,} بایت)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
