# Zeuz Agent

Zeuz Agent es el puente local entre la carpeta de programas CNC de una
computadora y el resto del ecosistema Zeuz. Corre en Windows, macOS y Linux,
publica una API HTTP local versionada y se anuncia por Bonjour/mDNS.

## Biblioteca y envío desde la computadora

La pestaña **Programas** de la interfaz Windows/Linux permite navegar por
carpetas, buscar nombres, consultar el código e importar archivos. Muestra la
biblioteca del servidor seleccionado; si no hay servidor, usa la carpeta de la
computadora. La importación conserva los bytes originales y agrega un sufijo
cuando el nombre ya existe. La vista previa muestra hasta 2 MiB; el envío usa
el programa completo.

Selecciona una CNC, pulsa **Enviar programa** y revisa el archivo y la máquina
en la confirmación. Agent prepara una copia completa en el Zeuz cuando hace
falta y consulta el progreso de esa misma CNC. **Cancelar envío** se dirige a
esa máquina aunque se seleccione otro programa. Si se pierde la confirmación,
el envío no se repite: se consulta su estado y se bloquean nuevas órdenes hasta
confirmar el resultado. No se pueden cambiar ni eliminar los datos de esa CNC
mientras tenga un envío pendiente de confirmar.

**Taller y conexión** conserva emparejamiento, servidor, perfiles, dispositivos,
actualizaciones y actividad. Cerrar la ventana deja el servidor en la bandeja
cuando el escritorio la ofrece.

## Aplicación de escritorio

La versión 0.4 incluye una interfaz Qt/QML para macOS y Windows que:

- inicia y detiene el servidor;
- sigue funcionando en la bandeja al cerrar la ventana;
- muestra el código de emparejamiento y las direcciones de red;
- permite elegir y abrir la carpeta de programas;
- reconoce ZeuzPresetter autorizado y recibe archivos de seteos para un Zeuz seleccionado;
- cambia el nombre visible del agente sin exponer puertos técnicos;
- detecta Orange Pi/ZeuzDNC en la red local;
- administra las máquinas del taller y su Orange Pi asignada;
- guarda baudrate, trama, flujo, terminador, DTR/RTS y modo goteo por máquina;
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

## Flujo de máquinas

Zeuz Agent es ahora la fuente de verdad de las máquinas. Los perfiles se
guardan en `machines.json`, junto a `config.json`. iZeuz selecciona una CNC y
el agente envía la orden a la Orange Pi asociada, incluyendo sus parámetros
seriales. La Orange Pi usa automáticamente su adaptador RS232; el operador ya
no elige `/dev/ttyUSBx`.

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
- `GET /v1/dnc/machines`
- `POST /v1/dnc/machine/select`
- `POST /v1/dnc/machine/save`
- `POST /v1/dnc/machine/delete`
- `POST /v1/dnc/send`
- `GET /v1/dnc/transfer/status`
- `POST /v1/dnc/send/cancel`
- `POST /v1/presetter/register`
- `GET /v1/presetter/clients`
- `GET /v1/presetter/targets`
- `POST /v1/presetter/jobs`

ZeuzPresetter descubre Agent por Bonjour o su dirección local, se empareja con el
mismo código y registra su presencia cada treinta segundos. Agent muestra la
aplicación conectada mientras su registro no supere noventa segundos. Los destinos
son las máquinas configuradas en Agent. La carga `{machine_id,filename,content}`
se guarda con un nombre único en `Presetter/` de la biblioteca activa: el servidor
compartido configurado en Agent, o la biblioteca local del Zeuz asignado cuando no
hay servidor. La respuesta indica `library_host`, `library_port` y `storage_scope`
(`workshop` o `device`). `status: "stored"` confirma almacenamiento;
no inicia el envío por RS232. Requiere firmware ZeuzDNC con `/api/workshop/content`.
El contenido debe ser ASCII, máximo 512 KiB, y el nombre debe terminar en `.txt`,
`.nc` o `.tap`, sin carpetas. La presencia indica la aplicación conectada, no la
conexión física de la regleta.

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

En Linux, este script agrega `dist/ZeuzAgent-linux-<arquitectura>.tar.gz`, con
ejecutable, icono e instalación opcional para el usuario mediante `install.sh`.
El flujo `.github/workflows/desktop-windows-linux.yml` compila y prueba
Windows x86_64 y Linux x86_64; se ejecuta manualmente o en una pull request y
guarda artefactos sin publicar un release. El build Linux de ese flujo requiere
Ubuntu 22.04/glibc 2.35 o posterior. Los binarios deben construirse y probarse en
su sistema operativo: las pruebas Qt locales en Mac no certifican un `.exe`
Windows ni un ejecutable Linux.

La nueva aplicación nativa Mac se construye desde el proyecto Xcode en
`../native/macos/`; el empaquetado Qt anterior se conserva para las otras
plataformas y no representa esa versión nativa.

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

### Servidor del taller y perfiles compartidos

En Agent, elige una Raspberry Pi u Orange Pi actualizada con **Usar servidor**
(o su hostname/puerto en Programas). La carpeta del PC sigue siendo la fuente
para archivos nuevos o modificados. La Pi conserva los archivos aunque se borren
en el PC y respalda los bytes reemplazados en `.zeuz-history` dentro de su carpeta
de programas. Los JSON de esa carpeta relacionan cada ruta con sus versiones.
Las ediciones hechas en la Pi o iPhone no se copian de vuelta al PC. Un archivo
sin cambios en el PC no reemplaza una edición del servidor.

El servidor atiende las consultas y ediciones de programas de iZeuz incluso
cuando Agent está disponible. Una vez confirmada la conexión al servidor, iZeuz
aprende su dirección automáticamente y puede continuar allí cuando la computadora
sale del taller. Los otros equipos Zeuz reciben la dirección del servidor para
leer y enviar sus programas directamente. Espera a que Agent indique
**Sincronizado** antes de retirar la computadora por primera vez; todos los equipos
involucrados requieren esta actualización de ZeuzDNC e iZeuz debe haber conectado
al menos una vez después de seleccionar el servidor.

Los perfiles se pueden editar en Agent, iPhone y la pantalla táctil. Cada Pi guarda
los perfiles de sus CNC; Agent conserva una copia y concilia cambios cada diez
segundos. Las revisiones evitan sobreescribir un editor desactualizado. Los cambios
simultáneos se muestran en Agent para elegir una versión; ambas quedan conservadas
en `workshop-sync.json`. Ese archivo también contiene el registro de sincronización:
no lo elimines para “reiniciar” una sincronización. **Pendiente** no confirma una
escritura remota. Los perfiles con diferencias impiden enviar desde Agent hasta
resolverlas. Los IDs locales repetidos de distintas Pi se identifican por separado.

**Renombrar** cambia el nombre visible y lo guarda en la Pi sin cambiar el hostname.
La búsqueda de equipos corre en segundo plano cada treinta segundos, conserva los
equipos conocidos desconectados y usa las direcciones IP de Bonjour cuando el
sistema no resuelve `.local`. Las órdenes de envío no se reintentan automáticamente.

Verificación de este cambio: `python -m unittest discover -s tests -q`; los contratos
HTTP y el escenario sin computadora se prueban en `ZeuzDNC/tests/test_workshop.py`
con `PYTHONPATH=../zeuzagent/src`. Ninguna de esas pruebas transmite a hardware CNC.

### Volver a abrir Agent con las Pi ya encendidas

Agent guarda ahora el inventario en `devices.json` junto a su configuración, incluso
para equipos que todavía no tienen una CNC asignada. Al abrir vuelve a comprobar
los hostnames conocidos, consulta los nombres de servicio SRV/TXT guardados y sondea
las API en paralelo. No depende de recibir otra vez el anuncio del arranque de la Pi.
Cada búsqueda crea su conexión Bonjour sobre las interfaces actuales; no reutiliza
sockets ni TTL de una sesión anterior.

La IP guardada sólo se usa para enrutar si la identidad estable de la Pi coincide.
Las versiones antiguas que sólo informan hostname siguen funcionando por DNS/Bonjour;
si únicamente contesta una IP antigua y no se puede confirmar el nombre, Agent muestra
esa respuesta sin autorizar silenciosamente el envío a una dirección que pudo cambiar
de propietario. Las versiones actualizadas de ZeuzDNC incluyen `device_id` en
`/api/info`, derivado del identificador de la placa o del sistema, sin escribir al leerlo.

### Actualizaciones de equipos

Las tarjetas de dispositivos muestran firmware y actualizaciones disponibles. Usa **Vincular** para autorizar la gestión, **Comprobar** para buscar y **Actualizar** para instalar; la Pi espera los envíos y continúa aunque cierres Agent. **Actualizar automáticamente** se activa individualmente y está desactivado de fábrica. Un equipo antiguo sin servicio OTA indica que necesita firmware compatible; Bonjour por sí solo no puede instalarlo.
