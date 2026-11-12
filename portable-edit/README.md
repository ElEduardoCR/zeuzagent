# ZEUZ Edit para Windows y Linux

Edición portable de escritorio, versión 0.2.0, basada en Qt/PySide6. Conserva la
estructura visual de ZEUZ Edit para Mac: explorador a la izquierda, pestañas y
editor al centro, herramientas a la derecha y envío en la parte inferior. Usa el
logo y el icono existentes. La versión nativa para Mac está en `../ZEUZ Edit` y
se abre con Xcode.

## Funciones disponibles

- Explorar una carpeta de programas, abrir archivos, cambiar entre pestañas,
  recientes y restaurar las rutas abiertas al salir.
- Editor monoespaciado con números de línea, color NC, comentarios, deshacer y
  rehacer, buscar y reemplazar, selección de herramienta y navegación a línea o N.
- Guardado atómico, alerta de cambios externos, confirmación de cambios sin guardar
  y conservación de UTF-8/BOM o Latin-1 y finales de línea CRLF/CR/LF. Abrir y guardar
  sin modificar conserva los bytes originales. Un carácter incompatible con la
  codificación del archivo impide el guardado en vez de reemplazarlo silenciosamente.
- Numerar, renumerar, quitar N, ajustar F/S por porcentaje, quitar códigos M exactos,
  espaciado y mayúsculas de código sin modificar el texto de comentarios.
- Comparación de dos programas y diferencias en texto; análisis de herramientas,
  unidades, valores mínimos/máximos XYZ y avisos básicos.
- Conexión a Agent con su dirección/código, lista de máquinas, confirmación de envío,
  estado y cancelación. Cada envío utiliza el contenido actual del editor, guarda
  una copia con nombre único en la biblioteca de Agent y dirige la orden a la máquina
  elegida. No se repiten automáticamente órdenes de envío inciertas. El estado y la
  cancelación siguen dirigidos a esa misma máquina aunque cambies la selección.

El envío desde Edit requiere la actualización de Agent que incluye
`POST /v1/dnc/program/send`. Esa ruta comprueba y prepara el archivo completo en la
biblioteca que utiliza ZeuzDNC antes de iniciar RS232; permite enviar también cuando
la biblioteca de Agent está en la computadora. Una versión anterior devuelve una
indicación para actualizar y no se usa la ruta antigua como alternativa. iPhone
conserva su contrato anterior.

Si se pierde la respuesta de envío, un estado `idle` o un éxito de otro archivo no
desbloquea un segundo envío. Se espera confirmación del programa con su nombre único.
En firmware sin identificador de solicitud, una cancelación mientras la orden
original sigue incierta tampoco prueba que esa orden no vaya a comenzar después:
verifica directamente el equipo antes de reiniciar la sesión para volver a enviar.

Los tokens de Agent se guardan en la configuración del usuario; en sistemas POSIX
el archivo tiene permisos 0600. No se imprimen tokens ni códigos en los registros.
Los perfiles se administran en Agent, que sigue siendo la fuente de verdad.

## Ejecutar desde código

Requiere Python 3.10 o posterior. En Windows:

```powershell
py -3 -m venv .venv
.venv/Scripts/python.exe -m pip install -e .
.venv/Scripts/python.exe -m zeuzedit_desktop
```

En Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m zeuzedit_desktop
```

Qt utiliza el tema y los controles de la plataforma. Las preferencias, rutas
recientes y el tamaño de letra se guardan en la carpeta de configuración del usuario.
Los programas originales no se mueven al abrirlos.

## Compilar aplicaciones independientes

Primero Windows, desde Windows:

```powershell
./scripts/build_windows.ps1
```

Después Linux, desde Linux:

```sh
./scripts/build_linux.sh
```

La salida es la carpeta completa `dist/ZeuzEdit`, con `ZeuzEdit.exe` en Windows o
`ZeuzEdit` en Linux. Conserva las dependencias que acompañan al ejecutable. Estos
scripts no publican ni instalan la app. El flujo de GitHub Actions compila Windows
y luego Linux, y guarda artefactos del flujo; no crea releases.

## Verificación y límites actuales

```sh
python -m unittest discover -s tests -v
QT_QPA_PLATFORM=offscreen python -m zeuzedit_desktop --smoke-test
```

Las pruebas cubren conservación de archivos/codificaciones/finales de línea,
comentarios y transformaciones, deshacer, Unicode, cancelación del cierre y el
contrato HTTP con un Agent simulado. No envían a una CNC real. El smoke test crea
una captura `zeuzedit-smoke.png` con contenido sintético.

Esta edición todavía no alcanza todas las funciones avanzadas de Mac: no incluye
puerto serial directo, comparación alineada por bloques, simulación de trayectorias,
estimación de mecanizado, múltiples raíces simultáneas ni recuperación automática de
documentos sin guardar tras un cierre inesperado. El análisis XYZ muestra valores
escritos y no representa la trayectoria resultante de offsets, ciclos o G91.

El editor admite archivos locales de hasta 32 MiB. Las cargas por Agent respetan su
límite de cuerpo JSON de 4 MiB; un archivo mayor debe guardarse directamente en la
biblioteca y enviarse desde Agent. Los binarios Windows/Linux deben compilarse y
probarse en su sistema operativo; ejecutar las pruebas en Mac no valida un binario
de Windows.
