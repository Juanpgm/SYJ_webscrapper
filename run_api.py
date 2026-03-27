"""
Punto de entrada para la API REST del SYJ WebScrapper.

Uso:
    python run_api.py
    python run_api.py --host 0.0.0.0 --port 8000 --reload
"""
import argparse
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SYJ WebScrapper API")
    parser.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Puerto (default: 8000)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload en desarrollo")
    args = parser.parse_args()

    uvicorn.run(
        "api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
