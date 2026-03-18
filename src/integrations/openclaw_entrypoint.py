from __future__ import annotations

import argparse
import json
import sys

from src.pipeline.orchestrator import run_cli


def main() -> None:
    parser = argparse.ArgumentParser(description="Entrypoint para ejecutar el pipeline desde OpenClaw")
    parser.add_argument("--fuentes", nargs="*", default=None, help="Filtro opcional de fuentes")
    parser.add_argument("--html-only", action="store_true", help="Guarda solo HTML para corrida rapida")
    parser.add_argument("--include-social", action="store_true", help="Incluye conectores sociales MVP")
    parser.add_argument("--social-only", action="store_true", help="Ejecuta solo conectores sociales")
    args = parser.parse_args()

    argv = ["main.py"]
    if args.fuentes:
        argv.extend(["--fuentes", *args.fuentes])
    if args.html_only:
        argv.append("--html-only")
    if args.include_social:
        argv.append("--include-social")
    if args.social_only:
        argv.append("--social-only")

    original_argv = sys.argv
    try:
        sys.argv = argv
        run_cli()
        print(json.dumps({"status": "ok", "exit_code": 0}, ensure_ascii=False))
    except Exception:
        print(json.dumps({"status": "error", "exit_code": 1}, ensure_ascii=False))
        raise
    finally:
        sys.argv = original_argv


if __name__ == "__main__":
    main()
