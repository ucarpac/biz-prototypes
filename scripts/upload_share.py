#!/usr/bin/env python3
import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.lower()).strip("-._")
    return slug[:60] or "share"


def run(cmd: list[str], dry_run: bool) -> None:
    print("+ " + " ".join(cmd), file=sys.stderr)
    if not dry_run:
        subprocess.run(cmd, check=True)


def require_gcloud() -> None:
    if shutil.which("gcloud") is None:
        raise SystemExit("gcloud command is required")


def object_prefix(args: argparse.Namespace) -> str:
    if args.dest_prefix:
        return args.dest_prefix.strip("/")

    stamp = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y%m%d-%H%M%S")
    base = slugify(args.slug or args.title or Path(args.source).stem)
    if args.scope == "agency":
        return f"shares/{args.partner}/{stamp}-{base}"
    return f"shares/internal/{stamp}-{base}"


def public_url(base_url: str, key: str) -> str:
    if not base_url:
        return key
    return base_url.rstrip("/") + "/" + key.lstrip("/")


def upload(args: argparse.Namespace) -> str:
    require_gcloud()
    bucket = args.bucket or os.environ.get("BIZ_PROTO_BUCKET")
    if not bucket:
        raise SystemExit("BIZ_PROTO_BUCKET or --bucket is required")

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise SystemExit(f"source not found: {source}")

    prefix = object_prefix(args)
    dest = f"gs://{bucket}/{prefix}"

    if source.is_dir():
        run(["gcloud", "storage", "rsync", str(source), dest, "--recursive"], args.dry_run)
        key = prefix.rstrip("/") + "/index.html"
    else:
        name = "index.html" if source.suffix.lower() in {".html", ".htm"} else source.name
        run(["gcloud", "storage", "cp", str(source), f"{dest.rstrip('/')}/{name}"], args.dry_run)
        key = prefix.rstrip("/") + "/" + name

    return public_url(args.base_url or os.environ.get("BIZ_PROTO_BASE_URL", ""), key)


def main() -> int:
    parser = argparse.ArgumentParser(description="biz-prototypes private share uploader")
    parser.add_argument("source", help="アップロードするHTMLファイルまたはディレクトリ")
    parser.add_argument("--scope", choices=["internal", "agency"], default="internal")
    parser.add_argument("--partner", default="ayudante")
    parser.add_argument("--title", default="")
    parser.add_argument("--slug", default="")
    parser.add_argument("--dest-prefix", default="")
    parser.add_argument("--bucket", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    url = upload(args)
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
