from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.utils.logging_config import configure_logging


def _load_config(root: Path) -> dict:
    config_path = root / "config" / "scraper_config.yaml"
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def _build_pipeline_command(fuentes: list[str] | None = None) -> list[str]:
    cmd = [sys.executable, "main.py"]
    if fuentes:
        cmd.extend(["--fuentes", *fuentes])
    return cmd


def run_once(*, fuentes: list[str] | None = None) -> int:
    cmd = _build_pipeline_command(fuentes=fuentes)
    process = subprocess.run(cmd, check=False)
    return int(process.returncode)


def run_scheduler(*, root: Path, fuentes: list[str] | None = None) -> None:
    configure_logging()
    log = logging.getLogger("scheduler")

    config = _load_config(root)
    timezone = config.get("timezone", "America/Bogota")
    schedule_hours = config.get("schedule_hours", [6, 18])
    schedule_minute = int(config.get("schedule_minute", 0))

    scheduler = BlockingScheduler(timezone=ZoneInfo(str(timezone)))

    def _job() -> None:
        log.info("Iniciando corrida programada")
        code = run_once(fuentes=fuentes)
        if code == 0:
            log.info("Corrida programada completada")
            return
        log.error("Corrida programada termino con error (exit=%s)", code)

    for hour in schedule_hours:
        trigger = CronTrigger(hour=int(hour), minute=schedule_minute, timezone=ZoneInfo(str(timezone)))
        scheduler.add_job(
            _job,
            trigger=trigger,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=900,
            id=f"pipeline_{hour:02d}{schedule_minute:02d}",
            replace_existing=True,
        )

    log.info(
        "Scheduler activo. Zona=%s, horas=%s, minuto=%s",
        timezone,
        schedule_hours,
        schedule_minute,
    )

    scheduler.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Scheduler local para corridas automaticas del scraper")
    parser.add_argument("--once", action="store_true", help="Ejecuta una sola corrida y termina")
    parser.add_argument("--fuentes", nargs="*", default=None, help="Filtro opcional de fuentes")
    args = parser.parse_args()

    root = Path.cwd()
    if args.once:
        raise SystemExit(run_once(fuentes=args.fuentes))

    run_scheduler(root=root, fuentes=args.fuentes)


if __name__ == "__main__":
    main()
