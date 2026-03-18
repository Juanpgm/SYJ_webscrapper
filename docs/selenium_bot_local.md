# Selenium Bot Local (MVP)

Bot local para automatizar navegacion en fuentes dinamicas cuando HTTP falle.

## Objetivo MVP

- Reusar el pipeline HTTP existente
- Escalar a navegador solo en sitios JS-heavy o con bloqueo
- Guardar HTML estable para parseo posterior

## Activacion

En `config/scraper_config.yaml`:

```yaml
use_selenium_scraper: true
selenium_timeout_seconds: 30
selenium_headless: true
```

Luego ejecutar:

```powershell
python main.py --fuentes el_pais_cali qhubo_cali
```

## Modo scheduler

```powershell
python run_scheduler.py
```

## YouTube social

Para scraping de comentarios de YouTube dentro del MVP social, el runner social levanta Selenium automáticamente cuando ejecutas:

```powershell
python main.py --include-social --social-only --fuentes youtube_cali
```

Si quieres reutilizar Selenium también para noticias dinámicas, activa además:

```yaml
use_selenium_scraper: true
```

Luego puedes ejecutar:

```powershell
python main.py --include-social --social-only --fuentes youtube_cali
```

## Señales de que debes usar Selenium

- Respuesta HTTP vacia o incompleta
- Sitio carga contenido por JS
- Bloqueo anti-bot en requests/cloudscraper

## Recomendaciones operativas

- Mantener Selenium desactivado por defecto para reducir consumo
- Activarlo por ventanas de tiempo o por fuente especifica
- Evitar concurrencia alta de navegador en host local
