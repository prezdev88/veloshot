#!/usr/bin/env bash

set -euo pipefail

readonly APP_ID="veloshot"
readonly INSTALL_ROOT="/opt/${APP_ID}"
readonly COMMAND_PATH="/usr/local/bin/${APP_ID}"
readonly DESKTOP_PATH="/usr/local/share/applications/${APP_ID}.desktop"
readonly ICON_PATH="/usr/local/share/icons/hicolor/scalable/apps/${APP_ID}.svg"

if [[ "${EUID}" -ne 0 ]]; then
    printf 'Error: ejecuta el desinstalador con: sudo ./uninstall.sh\n' >&2
    exit 1
fi

if [[ -L "${COMMAND_PATH}" ]]; then
    command_target="$(readlink -f -- "${COMMAND_PATH}" 2>/dev/null || true)"
    if [[ "${command_target}" == "${INSTALL_ROOT}/venv/bin/veloshot" ]]; then
        rm -- "${COMMAND_PATH}"
    fi
fi

rm -f -- "${DESKTOP_PATH}" "${ICON_PATH}"
rm -rf -- "${INSTALL_ROOT}"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$(dirname -- "${DESKTOP_PATH}")" >/dev/null 2>&1 || true
fi

printf 'VeloShot fue desinstalado. Las preferencias personales se conservaron.\n'
