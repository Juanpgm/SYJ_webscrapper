#!/usr/bin/env python3
"""
A/B benchmark: cloudflare vs requests vs auto-paralelo.
Ejecuta 3 corridas y genera tabla comparativa.
"""
import json
import subprocess
import re
from pathlib import Path
from datetime import datetime

def run_scraper(http_scraper_mode: str, name: str) -> dict:
    """Ejecuta una corrida del pipeline y extrae métricas."""
    print(f"\n{'='*60}")
    print(f"Iniciando benchmark: {name} (--http-scraper {http_scraper_mode})")
    print(f"{'='*60}")
    
    cmd = [
        ".venv/Scripts/python.exe",
        "main.py",
        "--fecha-desde", "10/03/2026",
        "--fecha-hasta", "11/03/2026",
        "--fuentes", "el_pais_cali", "blu_radio_cali", "qhubo_cali",
        "--http-scraper", http_scraper_mode,
        "--force-reprocess",
    ]
    if http_scraper_mode == "auto":
        cmd.append("--parallel-fetch")
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    output = result.stdout + result.stderr
    
    # Extrae métricas del log
    metrics = {
        "mode": http_scraper_mode,
        "name": name,
        "html_saved": 0,
        "json_saved": 0,
        "failed": 0,
        "skipped": 0,
        "urls_seen": 0,
        "fetcher_stats": {},
    }
    
    # Parse del resumen: {'sources': 3, 'urls_seen': 60, 'html_saved': 60, 'json_saved': 37, 'skipped': 23, 'failed': 0}
    resumen_match = re.search(r"Resumen: (\{[^}]+\})", output)
    if resumen_match:
        try:
            resumen = eval(resumen_match.group(1))
            metrics.update(resumen)
        except Exception:
            pass
    
    # Parse de comparativa fetchers: {'cloudflare': {...}, 'requests': {...}}
    comparativa_match = re.search(r"Comparativa fetchers HTTP: (\{[^}]+\})", output)
    if comparativa_match:
        try:
            fetcher_stats = eval(comparativa_match.group(1))
            metrics["fetcher_stats"] = fetcher_stats
        except Exception:
            pass
    
    return metrics

def main():
    print("\n" + "="*80)
    print("BENCHMARK A/B: Cloudflare vs Requests vs Auto-Paralelo")
    print(f"Fecha: {datetime.now().isoformat()}")
    print("="*80)
    
    results = []
    
    # Corre 3 variantes
    for http_mode, label in [
        ("cloudflare", "Cloudflare Only"),
        ("requests", "Requests Only"),
        ("auto", "Auto + Paralelo"),
    ]:
        try:
            metrics = run_scraper(http_mode, label)
            results.append(metrics)
            print(f"\n✓ {label} completado")
            print(f"  - URLs vistas: {metrics.get('urls_seen', 0)}")
            print(f"  - HTML guardados: {metrics.get('html_saved', 0)}")
            print(f"  - JSON guardados: {metrics.get('json_saved', 0)}")
            print(f"  - Fallidos: {metrics.get('failed', 0)}")
        except Exception as e:
            print(f"\n✗ {label} falló: {e}")
    
    # Tabla comparativa
    print("\n" + "="*80)
    print("TABLA COMPARATIVA")
    print("="*80)
    print(f"{'Modo':<20} {'URLs':<8} {'HTML':<8} {'JSON':<8} {'Failed':<8} {'Rate':<8}")
    print("-"*60)
    
    for r in results:
        urls = r.get("urls_seen", 0)
        html = r.get("html_saved", 0)
        json_cnt = r.get("json_saved", 0)
        failed = r.get("failed", 0)
        rate = f"{(json_cnt / max(1, urls) * 100):.1f}%" if urls else "0%"
        print(f"{r['name']:<20} {urls:<8} {html:<8} {json_cnt:<8} {failed:<8} {rate:<8}")
    
    # Detalle de fetchers HTTP
    print("\n" + "="*80)
    print("DETALLE DE FETCHERS HTTP (solo para auto-paralelo)")
    print("="*80)
    
    for r in results:
        if r["mode"] == "auto" and r.get("fetcher_stats"):
            print(f"\n{r['name']}:")
            fetchers = r["fetcher_stats"]
            print(f"{'Fetcher':<15} {'Attempts':<12} {'Wins':<10} {'Success':<10} {'Errors':<10}")
            print("-"*60)
            for fetcher_name, stats in fetchers.items():
                attempts = stats.get("attempts", 0)
                wins = stats.get("wins", 0)
                success = stats.get("success", 0)
                errors = stats.get("errors", 0)
                print(f"{fetcher_name:<15} {attempts:<12} {wins:<10} {success:<10} {errors:<10}")
    
    # Mostrar resumen de hallazgos
    print("\n" + "="*80)
    print("RECOMENDACIONES")
    print("="*80)
    
    json_rates = [(r["name"], r.get("json_saved", 0) / max(1, r.get("urls_seen", 1))) for r in results]
    best_mode = max(json_rates, key=lambda x: x[1])
    
    print(f"\n✓ Mejor tasa de éxito: {best_mode[0]} ({best_mode[1]*100:.1f}%)")
    print("✓ Recomendación: Usa el modo de mejor tasa para evitar rechazos.")
    print("✓ Próxima optimización: Paralelizar procesamiento de URLs dentro de fuentes.")
    
    # Guarda resultados en JSON
    output_file = Path("benchmark_results.json")
    output_file.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    print(f"\n✓ Resultados guardados en: {output_file}")

if __name__ == "__main__":
    main()
