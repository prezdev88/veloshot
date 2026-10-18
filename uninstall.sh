#!/usr/bin/env bash

set -euo pipefail

readonly APP_ID="veloshot"
readonly DATA_HOME="${XDG_DATA_HOME:-${HOME}/.local/share}"
readonly BIN_HOME="${XDG_BIN_HOME:-${HOME}/.local/bin}"
readonly INSTALL_ROOT="${DATA_HOME}/${APP_ID}"
readonly COMMAND_PATH="${BIN_HOME}/${APP_ID}"
readonly DESKTOP_PATH="${DATA_HOME}/applications/${APP_ID}.desktop"
readonly ICON_PATH="${DATA_HOME}/icons/hicolor/scalable/apps/${APP_ID}.svg"

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
