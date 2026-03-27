"""
Endpoints de autenticación de YouTube.

GET  /auth/youtube/status          → Estado actual de auth (cookies, PO token)
POST /auth/youtube/cookies         → Subir cookies.txt (multipart)
GET  /auth/youtube/cookies         → Info de cookies cargadas
DELETE /auth/youtube/cookies       → Eliminar cookies
POST /auth/youtube/po-token        → Generar/refrescar PO token manualmente
"""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from pydantic import BaseModel, Field

from src.auth.youtube_auth import (
    auth_status,
    clear_cookies,
    cookies_info,
    get_po_token,
    save_cookies,
)
from src.auth.browser_login import get_login_state, start_login

router = APIRouter(prefix="/auth/youtube", tags=["autenticación"])


class LoginRequest(BaseModel):
    timeout_seconds: int = Field(
        300,
        ge=30,
        le=600,
        description=(
            "Tiempo máximo en segundos para completar el login en el browser antes de cancelar. "
            "Por defecto 300 segundos (5 minutos). Rango: 30–600 s."
        ),
        examples=[300],
    )


@router.get("/status", summary="Estado de autenticación de YouTube")
def yt_auth_status():
    """
    Retorna el estado actual de autenticación:
    - **cookies**: Si hay un cookies.txt cargado (necesario para videos restringidos)
    - **po_token**: Si hay un PO Token activo (para videos públicos)
    """
    return auth_status()


@router.post("/cookies", summary="Subir cookies.txt exportadas del browser")
async def upload_cookies(file: UploadFile = File(..., description="Archivo cookies.txt en formato Netscape")):
    """
    Sube el archivo `cookies.txt` exportado de tu browser para autenticar yt-dlp.

    **Cómo exportar cookies de YouTube:**

    **Chrome/Edge:**
    1. Instala la extensión **"Get cookies.txt LOCALLY"**
    2. Ve a `https://www.youtube.com` (asegúrate de estar logueado)
    3. Haz clic en la extensión → **Export** → guarda como `cookies.txt`
    4. Sube el archivo aquí

    **Firefox:**
    1. Instala la extensión **"cookies.txt"**
    2. Ve a `https://www.youtube.com`
    3. Haz clic en la extensión → descarga el archivo
    4. Sube el archivo aquí

    El archivo debe estar en **formato Netscape** (la primera línea es `# Netscape HTTP Cookie File`).
    """
    if not file.filename:
        raise HTTPException(status_code=422, detail="No se proporcionó archivo.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="El archivo está vacío.")

    # Validar que parece un cookies.txt de Netscape
    text_sample = content[:500].decode("utf-8", errors="ignore").lower()
    if "netscape" not in text_sample and "youtube" not in text_sample and "#" not in text_sample:
        raise HTTPException(
            status_code=422,
            detail=(
                "El archivo no parece ser un cookies.txt válido en formato Netscape. "
                "Debe empezar con '# Netscape HTTP Cookie File'."
            ),
        )

    path = save_cookies(content)
    info = cookies_info()
    return {
        "message": "Cookies guardadas correctamente.",
        "path": str(path),
        **info,
    }


@router.get("/cookies", summary="Info de cookies cargadas")
def get_cookies_info():
    """Retorna información sobre las cookies de YouTube actualmente cargadas."""
    info = cookies_info()
    if not info.get("exists"):
        raise HTTPException(
            status_code=404,
            detail=(
                "No hay cookies cargadas. "
                "Súbelas via POST /auth/youtube/cookies. "
                "Ver instrucciones en el endpoint."
            ),
        )
    return info


@router.delete("/cookies", summary="Eliminar cookies guardadas")
def delete_cookies():
    """Elimina el archivo cookies.txt almacenado."""
    if not cookies_info().get("exists"):
        raise HTTPException(status_code=404, detail="No hay cookies que eliminar.")
    clear_cookies()
    return {"message": "Cookies eliminadas."}


@router.post("/login", summary="Login de Google/YouTube via Chrome (OAuth browser)")
def browser_login(req: LoginRequest = LoginRequest()):
    """
    Abre una ventana de Chrome para que el usuario inicie sesión con su cuenta de Google.

    **Flujo:**
    1. Se abre Chrome con la página de login de Google para YouTube
    2. El usuario completa el login normalmente (OAuth real de Google)
    3. El sistema detecta el login y captura automáticamente las cookies de sesión
    4. Las cookies quedan listas para yt-dlp

    **Consulta el estado con:** `GET /auth/youtube/login/status`

    Timeout configurable (default: 300 segundos = 5 minutos).
    """
    return start_login(timeout_seconds=req.timeout_seconds)


@router.get("/login/status", summary="Estado del proceso de login via browser")
def login_status():
    """
    Retorna el estado actual del proceso de login iniciado con `POST /auth/youtube/login`.

    Estados posibles:
    - `idle` — no se ha iniciado login
    - `waiting_login` — browser abierto, esperando que el usuario se loguee
    - `capturing` — login detectado, capturando cookies
    - `done` — cookies exportadas exitosamente
    - `error` — falló el proceso (ver campo `error`)
    """
    return get_login_state()


@router.post("/po-token", summary="Generar/refrescar PO Token")
def refresh_po_token():
    """
    Genera un nuevo PO Token (Proof of Origin) usando el generador Node.js.

    El PO Token permite a yt-dlp acceder a videos públicos de YouTube
    sin necesidad de cookies. Se renueva automáticamente cada 5 minutos.

    **Requiere:** `youtube-po-token-generator` instalado via npm:
    ```
    npm install -g youtube-po-token-generator
    ```
    """
    tokens = get_po_token(force_refresh=True)
    if not tokens:
        raise HTTPException(
            status_code=503,
            detail=(
                "No se pudo generar el PO Token. "
                "Instala el generador: npm install -g youtube-po-token-generator"
            ),
        )
    return {
        "message": "PO Token generado correctamente.",
        "visitor_data": tokens.get("visitorData", "")[:20] + "...",  # no exponer completo
        "po_token_preview": tokens.get("poToken", "")[:20] + "...",
    }
