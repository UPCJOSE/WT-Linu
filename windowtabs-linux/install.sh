#!/usr/bin/env bash
# Instala WindowTabs Linux: motor de KWin + interfaz (barra de pestañas)
set -e
cd "$(dirname "$0")"

# 1) dependencias (CachyOS / Arch)
if ! python3 -c "import PySide6, jeepney" 2>/dev/null; then
  echo "Faltan paquetes de Python. Instalando con pacman (pide tu contraseña)..."
  sudo pacman -S --needed pyside6 python-jeepney
fi

# 2) interfaz
DEST="$HOME/.local/share/windowtabs/ui"
rm -rf "$DEST"
mkdir -p "$DEST" "$HOME/.local/bin" "$HOME/.local/share/applications"
cp -r ui/windowtabs_ui "$DEST/"
cat > "$HOME/.local/bin/windowtabs-ui" <<LAUNCH
#!/bin/sh
cd "$DEST" && exec python3 -m windowtabs_ui "\$@"
LAUNCH
chmod +x "$HOME/.local/bin/windowtabs-ui"
cat > "$HOME/.local/share/applications/windowtabs-ui.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=WindowTabs Linux
Comment=Pestañas para agrupar ventanas
Exec=$HOME/.local/bin/windowtabs-ui
Icon=window-duplicate
Categories=Utility;
DESK

# 3) motor de KWin
kpackagetool6 --type=KWin/Script --upgrade ./kwin-script/windowtabslinux 2>/dev/null \
  || kpackagetool6 --type=KWin/Script --install ./kwin-script/windowtabslinux
kwriteconfig6 --file kwinrc --group Plugins --key windowtabslinuxEnabled true
# recargar el motor (si ya estaba cargado, así toma la versión nueva)
qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript windowtabslinux >/dev/null 2>&1 || true
qdbus6 org.kde.KWin /KWin reconfigure

# 4) abrir la interfaz
pkill -f "windowtabs_ui" 2>/dev/null || true
nohup "$HOME/.local/bin/windowtabs-ui" >/dev/null 2>&1 &
echo
echo "Listo. Busca el icono de WindowTabs en la bandeja del sistema."
echo "Para crear un grupo: clic derecho en el icono > Crear grupo..."
