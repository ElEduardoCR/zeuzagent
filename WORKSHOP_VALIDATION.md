# Validación del servidor de taller

Esta implementación conserva los cambios que ya estaban en los tres repositorios.
No instala firmware, reinicia equipos físicos ni inicia transmisiones CNC reales.

## Contratos comprobados

- HTTP local real: copiar bytes del PC a la Pi; apagar Agent; listar/leer programas,
  editar perfiles y atender un envío interceptado desde `/v1` de la Pi; conciliar al
  reconectar Agent. El servidor enruta también a una segunda Pi simulada.
- Cliente Swift de producción: aprende el servidor, cambia al fallar el PC, conserva
  el destino entre instancias y no repite un POST cuyo resultado es incierto.
- Persistencia: versiones reemplazadas, borrados de programas conservados, archivos
  faltantes recuperados, alias de equipos, perfiles, conflictos y resolución tras
  reiniciar el sincronizador.
- Concurrencia: revisiones de contenido compatibles entre Agent/Pi/Swift/QML,
  escrituras condicionales, rechazo de ediciones desactualizadas y archivos de
  perfiles protegidos entre API y proceso touch.
- Descubrimiento: un segundo anuncio Bonjour se incorpora después del primero;
  falla de lectura provoca nueva búsqueda; las órdenes de envío no se repiten.
- El QML de Agent carga sin errores y se revisó a 820 px y 1100 px, con paletas clara
  y oscura. El editor touch conserva la revisión abierta en su formulario.
- iZeuz compila para iOS Simulator. La validación automatizada del cliente no
  sustituye una prueba en el iPhone físico.

## Interfaz

La pantalla mantiene el vocabulario del taller: programas, máquinas y dispositivos.
Los estados incluyen texto; las acciones personalizadas tienen foco de teclado.
Los controles de conexión y perfiles permanecen junto a su información. La paleta
usa roles compartidos para ambas apariencias. Contrastes calculados: texto principal
14.64:1 claro / 14.13:1 oscuro; texto secundario sobre superficie elevada 5.12:1 /
7.30:1; acciones sobre superficie elevada 4.93:1 / 7.17:1. No se añadieron animaciones.

Criterios aplicados de apple-design: `accessibility.md`, visión y controles;
`feedback.md`, estado integrado en la interfaz; `settings.md`, opciones en contexto.

## Comandos

Desde `zeuzagent`:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -q
```

Desde `ZeuzDNC`:

```sh
PYTHONPATH=../zeuzagent/src .venv/bin/python -m unittest discover -s tests -q
```

Desde `ZEUZ for iOS`:

```sh
bash Tools/verify_workshop.sh
xcodebuild -project ZeuzDNC.xcodeproj -scheme ZeuzDNC -sdk iphonesimulator \
  -configuration Debug CODE_SIGNING_ALLOWED=NO build
```

## Pendiente en hardware

Actualizar conjuntamente Agent, iZeuz y ZeuzDNC; seleccionar el servidor; esperar
confirmación de sincronización; conectar iZeuz para que aprenda la Pi; retirar la
computadora y comprobar con programas de prueba. La aclaración posterior identifica
la Orange Pi asociada a `fadal`, accesible como `zeuz.local`. La consulta de sólo lectura
confirmó ese hostname y versión instalada 0.6.0. Faltan el modelo exacto y los registros
durante el fallo; el corte prematuro de Bonjour no demuestra la causa física.


## Llegada tardía del cliente — 22 de septiembre de 2026

Escenario correcto: ambas Pi siguen encendidas; Agent se cierra, la computadora sale
durante horas y luego vuelve a abrir Agent. La Orange Pi asociada a `fadal` sólo
reaparecía tras reiniciarla. No se trata de una desconexión espontánea durante uso.

Evidencia de sólo lectura en esta sesión:

- La configuración local contiene `zeuz.local` (grafía con **z** al final).
- DNS y Bonjour lo resolvieron a `192.168.1.99`; `/api/info` respondió hostname `zeuz`,
  servicio `zeuz-dnc`, versión `0.6.0`. `/api/machines` contiene ID `fadal`, nombre
  visible `Fadal`. Las mayúsculas no intervienen en la búsqueda de red.
- El equipo también respondió con el nuevo sondeo de hostname conocido, suprimiendo
  deliberadamente la lista Bonjour en el cliente de prueba. No se modificó la Pi.
- El otro hostname de la configuración, `zeuz-dnc-1b3b992.local`, no resolvió durante
  esta comprobación. Esto no demuestra que el dispositivo estuviera apagado.
- La imagen Orange Pi usa un servicio estático de Avahi y hostname fijo `zeuz`.
  Eso permite una posible colisión si otra imagen usa el mismo hostname; no se observó
  ni se confirmó tal colisión. No se cambió ese hostname ni se añadieron reinicios.

Correcciones adicionales: inventario persistente, restauración al reabrir Agent,
consulta activa de servicios conocidos aunque falte la respuesta PTR, sondeos HTTP
paralelos, validación de identidad al recuperar una IP y descarte de direcciones que
ahora correspondan a otro equipo. `/api/info` de ZeuzDNC incorpora identidad estable
sin provocar escrituras al consultarlo.

Validación final: **23 pruebas Agent y 34 ZeuzDNC aprobadas**. La nueva prueba mDNS
usa UDP real exclusivamente por loopback: dos servicios permanecen registrados, se
cierra el primer cliente, vencen TTL de un segundo y un segundo cliente completamente
nuevo encuentra ambos sin reiniciar los anunciantes. El TTL corto modela la caducidad
de caché; no prueba horas reales de inactividad del controlador Wi-Fi o de Avahi en la
Orange Pi instalada. También se probaron pérdida de PTR, cambio de IP, interfaz que
vuelve después, reapertura de DesktopBackend y rechazo de una IP reasignada.

Si el fallo físico reaparece, ejecutar **sin reiniciar previamente** el script de sólo
lectura `ZeuzDNC/image/diagnostic/collect_discovery.sh` en la Pi y conservar su salida.
Recoge uptime, estado y registros de Avahi/NetworkManager, interfaces, multicast y
API; no reinicia servicios ni cambia la red. No pudo ejecutarse remotamente durante
esta sesión: no hay una sesión de administración disponible. No hubo despliegues,
reinicios físicos ni órdenes CNC.

## OTA sin pantalla (22 septiembre 2026)

Se agregó administración por equipo en Agent y Estado de Zeuz en iPhone: anuncio disponible, comprobar, confirmar instalación, fases/bytes de descarga, reconexión y opción automática desactivada de fábrica. Pi ejecuta el trabajo autorizado sin mantener conectado el cliente. Las Pi sin capacidad OTA muestran la necesidad del firmware inicial; no se simula una actualización sobre los equipos 0.6.0 actuales.

Contrato y empaquetado detallados: `../ZeuzDNC/REMOTE_UPDATES.md`. Seguridad de gestión basada en Agent vinculado; no se publica el PIN móvil ni se permite cambiar rutas de taller sin autorización después de vincular. Agent adjunta el token en sus peticiones de sincronización/configuración a una Pi vinculada.

Pruebas: 50 DNC y 23 Agent aprobadas en unittest; integración Swift `Tools/verify_workshop.sh` con cliente real, autorización OTA, reconexión y no repetición de POST incierto; Xcode Simulator Debug BUILD SUCCEEDED. Logs de trabajo: `/tmp/zeuz-ota-dnc-tests.log`, `/tmp/zeuz-ota-agent-tests.log`, `/tmp/zeuz-ota-ios-build.log`. Se detectó y corrigió la selección de la implementación predeterminada del protocolo Swift al omitir argumentos; la prueba usa el mismo cliente existencial que la app.

No se instalaron cambios en las Pi ni se reiniciaron servicios reales. La publicación, construcción de imágenes y despliegue pertenecen a la tarea de release. Sigue pendiente probar el instalador/polkit/recuperación con la imagen final sobre hardware, y el primer acceso físico a equipos antiguos que no admiten OTA ni SSH.
