Zeuz Agent para Linux

Descomprime el paquete y ejecuta ./ZeuzAgent o ./install.sh.
La instalación es para tu usuario y no requiere sudo.
No necesitas instalar Python ni Qt por separado.

El paquete debe coincidir con la arquitectura de tu equipo.
Los builds de CI se generan en Ubuntu 22.04 para x86_64 y requieren
glibc 2.35 o posterior. En un escritorio Linux con X11/Wayland pueden
necesitarse las bibliotecas del sistema EGL/OpenGL y xcb-cursor.

Configuración y perfiles: ~/.config/zeuz/ (o XDG_CONFIG_HOME/zeuz/).
La carpeta de programas puede elegirse en Taller y conexión.
Cerrar la ventana conserva el servidor si hay bandeja del sistema.
Salir detiene Agent; las transmisiones ya aceptadas por ZeuzDNC
continúan bajo control del equipo Zeuz.

Programas permite navegar, buscar, importar, consultar y enviar programas.
Selecciona la CNC y revisa el nombre del archivo antes de confirmar.
Un envío sin confirmación se consulta; nunca se repite automáticamente.
