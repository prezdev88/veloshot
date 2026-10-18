# VeloShot

Aplicación de escritorio independiente en **Python + Qt 6/PySide6**, construida a partir del análisis de comportamiento de Flameshot 14. Incluye el flujo de captura y anotación local y una interfaz inspirada en la observada. No es una copia exacta de todas las funciones de Flameshot.

VeloShot es un proyecto independiente y no está afiliado con Flameshot.

## Requisitos

- Linux con una sesión gráfica **X11**. La captura de escritorio en Wayland aún no está implementada.
- Python 3.10 o superior.
- Acceso a Internet durante la primera instalación para descargar PySide6.

El editor puede abrir imágenes existentes en cualquier plataforma compatible con PySide6, pero la captura directa del escritorio actualmente depende de X11.

## Instalación recomendada

Descarga o clona el repositorio y ejecuta el instalador desde su carpeta:

```bash
git clone https://github.com/prezdev88/veloshot.git
cd veloshot
./install.sh
```

El instalador trabaja únicamente dentro de tu usuario y no necesita `sudo`. Crea un entorno aislado en `~/.local/share/veloshot`, instala el comando en `~/.local/bin/veloshot` y añade VeloShot al menú de aplicaciones con su icono. Después puedes borrar la carpeta del código fuente y ejecutar:

```bash
veloshot launcher
```

También puedes buscar **VeloShot** en el menú de aplicaciones. Si la terminal todavía no reconoce el comando, abre una sesión nueva o añade `~/.local/bin` a `PATH`; la entrada del menú utiliza una ruta absoluta y seguirá funcionando.

En Debian o Ubuntu, si faltan las bibliotecas de Qt, instálalas antes de repetir `./install.sh`:

```bash
sudo apt update
sudo apt install python3 python3-venv libdbus-1-3 libegl1 libfontconfig1 libgl1 libglib2.0-0 libxkbcommon0
```

Para actualizar una instalación existente, descarga los cambios del repositorio y vuelve a ejecutar `./install.sh`. Para desinstalarla:

```bash
./uninstall.sh
```

El desinstalador conserva las preferencias personales de VeloShot.

## Instalar y ejecutar desde el código fuente

Después de descargar el ZIP del proyecto o clonarlo con Git, abre una terminal dentro de su carpeta y crea un entorno virtual:

```bash
cd veloshot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

La opción `-e` instala el proyecto en modo editable: los cambios realizados en el código se aplican sin reinstalarlo. Para una instalación normal, usa `python -m pip install .`.

Puedes iniciar la aplicación con el script incluido:

```bash
./run.sh launcher
```

O mediante el comando instalado en el entorno virtual:

```bash
veloshot launcher
```

El lanzador añade un icono a la bandeja cuando el escritorio la ofrece. Para iniciar directamente una captura o abrir la configuración:

```bash
veloshot gui
veloshot config
```

Cuando termines, puedes salir del entorno virtual con `deactivate`.

## Crear un paquete instalable

Python no necesita compilar la aplicación a código nativo. Si quieres generar paquetes distribuibles, instala la herramienta de construcción y crea un wheel y un archivo fuente:

```bash
source .venv/bin/activate
python -m pip install build
python -m build
```

Los archivos se crean en `dist/`. El wheel se puede copiar e instalar en otro equipo compatible:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install dist/veloshot-*.whl
veloshot launcher
```

Para verificar la instalación desde el código fuente:

```bash
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
veloshot --version
```

Si hay varios monitores, el lanzador muestra un selector **Pantalla**, con el nombre y la resolución de cada monitor y la opción **Todas las pantallas**. Tanto la selección de un área como el botón Pantalla completa respetan esa elección. Desde la bandeja o `./run.sh gui` aparece un diálogo para elegir antes de capturar. Las regiones explícitas por CLI conservan sus coordenadas de escritorio.

La captura está implementada para **X11**, como la sesión local accesible mediante `DISPLAY`. El editor de imágenes existentes también funciona sin captura de escritorio:

```bash
./run.sh edit /ruta/imagen.png
```

## Funciones

- Selección rectangular, movimiento, ocho tiradores y ajuste por teclado.
- Lápiz, línea, flecha, rectángulo, rectángulo relleno, círculo, marcador, texto, contador, pixelado e inversión.
- Color, grosor, figuras con relleno, trazos rectos y proporciones con Mayús.
- Deshacer y rehacer; guardado PNG/JPEG/BMP y portapapeles de imagen.
- Capturas fijadas sobre el escritorio: arrastrar, girar, cambiar opacidad, copiar, guardar y cerrar.
- Lanzador con retardo, bandeja, configuración persistente y edición de archivos.
- CLI con monitores, regiones, última selección, PNG en stdout y aceptación al seleccionar.

| Acción durante la captura | Tecla |
| --- | --- |
| Copiar / guardar | Ctrl+C / Ctrl+S |
| Aceptar las opciones de CLI | Enter |
| Deshacer / rehacer | Ctrl+Z / Ctrl+Mayús+Z o Ctrl+Y |
| Seleccionar todo / selección | Ctrl+A / S |
| Lápiz, línea, flecha | P, L, A |
| Rectángulo, relleno, círculo | R, F, C |
| Marcador, texto, contador | M, T, N |
| Pixelado / inversión | B / I |
| Mover selección | V, luego arrastrar |
| Panel lateral | Espacio o Tab |
| Mover / cambiar tamaño 1 px | Flechas / Mayús+flechas |
| Color / grosor | Clic derecho / rueda |
| Cancelar | Esc |

Para un atajo global, asigna la ruta absoluta de `run.sh gui` —por ejemplo, `/ruta/al/proyecto/run.sh gui`— a Impr Pant en la configuración de teclado de tu escritorio. También puedes usar `veloshot gui` si el entorno virtual está activo o si instalaste el paquete globalmente. El instalador no cambia automáticamente la configuración del sistema ni la de Flameshot.

## Comandos

```bash
./run.sh full -p /tmp/pantalla.png
./run.sh screen -n 0 --raw > /tmp/monitor.png
./run.sh screen --region 800x600+100+50 -p /tmp/region.png
./run.sh screen -e
./run.sh gui --region 800x600+100+50 -p /tmp/captura.png
./run.sh gui --last-region --clipboard
./run.sh gui --accept-on-select --raw > /tmp/seleccion.png
./run.sh gui --pin
./run.sh gui --print-geometry
```

`-d` expresa milisegundos. `--region` usa coordenadas del escritorio y admite orígenes negativos. `screen` elige por defecto el monitor del cursor. `--raw` produce exclusivamente PNG en stdout. Con `gui`, Enter acepta el destino solicitado y Ctrl+S/Ctrl+C conservan sus acciones explícitas.

En X11, el proceso conserva la propiedad del portapapeles después de cerrar el editor; permanece activo hasta que otra aplicación reemplaza su contenido, o hasta salir desde la bandeja. Así otros procesos pueden recuperar la imagen.

La configuración propia usa `QSettings("VeloShot", "VeloShot")`. Al iniciar por primera vez, VeloShot migra automáticamente las preferencias guardadas por versiones anteriores bajo el nombre FlareShot. Abrir una imagen mayor que la pantalla la reduce para editarla; las capturas se componen en píxeles lógicos del escritorio.

## Verificación y análisis

Se verificaron **55 pruebas automatizadas** y **11 escenarios del ejecutable en una pantalla X11 virtual**, incluida la transferencia de la imagen del portapapeles entre procesos. También se comprobó el selector con dos pantallas X11 virtuales de distinta resolución: captura los píxeles elegidos, abre el editor en la pantalla correspondiente y copia su imagen.

También se verificó el lanzador con i3 en un escritorio virtual: el editor cubre toda la pantalla, copia la captura completa y permite seleccionar un área cerca del borde inferior derecho. El editor de captura evita que el gestor de ventanas lo reduzca a un mosaico.

El botón Guardar se prueba con el diálogo real bajo i3: permite elegir un archivo y guardar el PNG; Cancelar devuelve la selección y el teclado al editor. Al abrir diálogos, la superposición se oculta temporalmente para que no tape el selector de archivos, el selector de color o la entrada de texto.

```bash
QT_QPA_PLATFORM=offscreen python3 -m unittest discover -s tests -v
xvfb-run -a -s '-screen 0 1440x1000x24' dbus-run-session -- \
  python3 tools/verify_desktop.py --output analysis/rebuilt-delivery
xvfb-run -a -s '-screen 0 1440x1000x24' dbus-run-session -- \
  python3 tools/verify_tiling.py --output analysis/tiling-fixed
xvfb-run -a -s '-screen 0 1440x1000x24' dbus-run-session -- \
  python3 tools/verify_save_dialog.py --output analysis/save-fixed
xvfb-run -a -s '-screen 0 1024x768x24 -screen 1 800x600x24 -xinerama' \
  python3 tools/verify_monitor_picker.py --output analysis/monitor-picker
```

Quedan fuera de esta implementación el portal de captura Wayland, subida remota/Imgur, compatibilidad con la API D-Bus de Flameshot, historial de archivos y el listado de objetos con reordenamiento. Algunos iconos, atajos y controles difieren. La composición multimonitor tiene pruebas con geometrías simuladas y el selector con pantallas X11 virtuales; no se verificó con hardware de densidades distintas. No se afirma equivalencia total ni recuperación del código fuente original.

## Licencia

VeloShot se distribuye bajo la [licencia MIT](LICENSE).
