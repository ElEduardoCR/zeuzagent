# Zeuz Agent

Zeuz Agent es el puente local entre la carpeta de programas CNC de una
computadora y el resto del ecosistema Zeuz. Corre en Windows, macOS y Linux,
publica una API HTTP local versionada y se anuncia por Bonjour/mDNS.

## Aplicación de escritorio

La versión 0.2 incluye una interfaz Qt/QML que:

- inicia y detiene el servidor;
- sigue funcionando en la bandeja al cerrar la ventana;
- muestra el código de emparejamiento y las direcciones de red;
- permite elegir y abrir la carpeta de programas;
- cambia el nombre y puerto del agente;
- genera un código nuevo;
- revoca todos los tokens existentes;
- muestra la actividad HTTP reciente;
- puede iniciarse con la computadora.

Instalación para desarrollo:

```powershell
cd C:\zeuz_ecosystem_v1\zeuzagent
.\.venv\Scripts\python.exe -m pip install -e ".[desktop]"
.\.venv\Scripts\zeuzagent-ui.exe
```

También puede abrirse desde la CLI:

```powershell
.\.venv\Scripts\zeuzagent.exe ui
```

En macOS/Linux sustituye `.venv\Scripts\` por `.venv/bin/`.

La configuración se guarda en:

- Windows: `%APPDATA%\Zeuz\Agent\config.json`
- macOS: `~/Library/Application Support/Zeuz/Agent/config.json`
- Linux: `~/.config/zeuz/agent.json`

## CLI

La CLI se conserva para servidores y diagnóstico:

```powershell
.\.venv\Scripts\zeuzagent.exe init --programs-dir "C:\Zeuz Programs"
.\.venv\Scripts\zeuzagent.exe run
.\.venv\Scripts\zeuzagent.exe show-config
```

La API escucha por defecto en el puerto `47820`.

## API v1

Rutas públicas:

- `GET /v1/health`
- `GET /v1/info`
- `POST /v1/pair`

Rutas con `Authorization: Bearer <token>`:

- `GET /v1/programs?path=`
- `GET /v1/programs/content?path=...`
- `GET /v1/programs/download?path=...`
- `PUT /v1/programs/content`
- `POST /v1/programs`
- `DELETE /v1/programs/content?path=...`
- `GET /v1/programs/search?q=...`
- `GET /v1/changes?since=...`

## Construir aplicación Windows

```powershell
.\scripts\build_desktop.ps1
```

El ejecutable se genera en:

```text
dist\ZeuzAgent.exe
```

Para macOS o Linux:

```bash
./scripts/build_desktop.sh
```

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
