#!/usr/bin/env bash
# Install Champions MetaDesk Studio for this user (no sudo): the app in ~/.local/opt, a launcher in
# ~/.local/bin, and a menu entry with its icon. Run it from the extracted archive. To remove it:
#   ./install.sh --uninstall
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="io.metadesk.champ"
DEST="${HOME}/.local/opt/champions-metadesk"
BIN="${HOME}/.local/bin/champions-metadesk"
DATA="${XDG_DATA_HOME:-${HOME}/.local/share}"
ENTRY="${DATA}/applications/${APP_ID}.desktop"

if [[ "${1:-}" == "--uninstall" ]]; then
  rm -rf "${DEST}" "${BIN}" "${ENTRY}"
  for size in 48 128 256 512; do rm -f "${DATA}/icons/hicolor/${size}x${size}/apps/champions-metadesk.png"; done
  echo "Removed. Your data stays in ${DATA}/champions-metadesk-studio."
  exit 0
fi

rm -rf "${DEST}"
mkdir -p "${DEST}" "$(dirname "${BIN}")" "${DATA}/applications"
cp -a "${HERE}/champions-metadesk/." "${DEST}/"
ln -sfn "${DEST}/champions-metadesk" "${BIN}"
for size in 48 128 256 512; do
  mkdir -p "${DATA}/icons/hicolor/${size}x${size}/apps"
  cp "${HERE}/icons/${size}.png" "${DATA}/icons/hicolor/${size}x${size}/apps/champions-metadesk.png"
done
# The app keeps this entry as it is (the =installed marker); without it, it writes a hidden one.
cat > "${ENTRY}" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Champions MetaDesk Studio
Comment=Competitive Pokémon Champions workbench: box, teams, meta, damage calc and matchup plans
Icon=champions-metadesk
Exec=${DEST}/champions-metadesk
Terminal=false
Categories=Game;Utility;
StartupWMClass=${APP_ID}
X-Champions-MetaDesk-Studio=installed
DESKTOP
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "${DATA}/applications" || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f "${DATA}/icons/hicolor" || true
echo "Installed. Start it from your app menu, or run: ${BIN}"
