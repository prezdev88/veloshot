#!/usr/bin/env bash

set -euo pipefail

readonly APP_ID="veloshot"
readonly PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PYTHON_BIN="${PYTHON:-python3}"
readonly DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
readonly BIN_HOME="${XDG_BIN_HOME:-${HOME}/.local/bin}"
readonly INSTALL_ROOT="${DATA_HOME}/${APP_ID}"
readonly VENV_DIR="${INSTALL_ROOT}/venv"
readonly COMMAND_PATH="${BIN_HOME}/${APP_ID}"
readonly DESKTOP_PATH="${DATA_HOME}/applications/${APP_ID}.desktop"
readonly ICON_PATH="${DATA_HOME}/icons/hicolor/scalable/apps/${APP_ID}.svg"

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

command -v "${PYTHON_BIN}" >/dev/null 2>&1 || \
    fail "No se encontró ${PYTHON_BIN}. Instala Python 3.10 o superior."

"${PYTHON_BIN}" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' || \
    fail "VeloShot requiere Python 3.10 o superior."

printf 'Instalando VeloShot en %s...\n' "${INSTALL_ROOT}"
mkdir -p "${INSTALL_ROOT}" "${BIN_HOME}" "$(dirname -- "${DESKTOP_PATH}")" \
    "$(dirname -- "${ICON_PATH}")"

if ! "${PYTHON_BIN}" -m venv "${VENV_DIR}"; then
    fail "No se pudo crear el entorno virtual. En Debian/Ubuntu instala python3-venv."
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade "${PROJECT_DIR}"

if ! QT_QPA_PLATFORM=offscreen "${VENV_DIR}/bin/python" -c \
    'from PySide6.QtGui import QImage; import veloshot'; then
    fail "PySide6 no pudo cargar sus bibliotecas del sistema. Revisa los requisitos del README."
fi

if [[ -e "${COMMAND_PATH}" || -L "${COMMAND_PATH}" ]]; then
    current_target="$(readlink -f -- "${COMMAND_PATH}" 2>/dev/null || true)"
    expected_target="$(readlink -f -- "${VENV_DIR}/bin/veloshot")"
    [[ "${current_target}" == "${expected_target}" ]] || \
        fail "${COMMAND_PATH} ya existe y no pertenece a esta instalación."
fi
ln -sfn "${VENV_DIR}/bin/veloshot" "${COMMAND_PATH}"

install -m 0644 "${PROJECT_DIR}/veloshot.svg" "${ICON_PATH}"

desktop_tmp="${DESKTOP_PATH}.tmp.$$"
trap 'rm -f -- "${desktop_tmp}"' EXIT
escaped_command="${COMMAND_PATH//\\/\\\\}"
escaped_command="${escaped_command//\"/\\\"}"
while IFS= read -r line || [[ -n "${line}" ]]; do
    if [[ "${line}" == Exec=* ]]; then
        printf 'Exec="%s" launcher\n' "${escaped_command}"
    else
        printf '%s\n' "${line}"
    fi
done < "${PROJECT_DIR}/VeloShot.desktop" > "${desktop_tmp}"
mv -- "${desktop_tmp}" "${DESKTOP_PATH}"
trap - EXIT

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$(dirname -- "${DESKTOP_PATH}")" >/dev/null 2>&1 || true
fi

"${COMMAND_PATH}" --version
printf '\nVeloShot quedó instalado.\n'
printf 'Comando: %s launcher\n' "${COMMAND_PATH}"
printf 'También puedes abrirlo desde el menú de aplicaciones.\n'
if [[ ":${PATH}:" != *":${BIN_HOME}:"* ]]; then
    printf 'Aviso: añade %s a PATH para usar "veloshot" directamente en nuevas terminales.\n' "${BIN_HOME}"
fi
