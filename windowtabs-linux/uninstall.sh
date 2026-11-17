#!/usr/bin/env bash
pkill -f "windowtabs_ui" 2>/dev/null || true
kwriteconfig6 --file kwinrc --group Plugins --key windowtabslinuxEnabled false
kpackagetool6 --type=KWin/Script --remove windowtabslinux
qdbus6 org.kde.KWin /KWin reconfigure
rm -rf "$HOME/.local/share/windowtabs" "$HOME/.local/bin/windowtabs-ui" \
       "$HOME/.local/share/applications/windowtabs-ui.desktop" \
       "$HOME/.config/autostart/windowtabs-ui.desktop"
echo "WindowTabs Linux quitado (tus ajustes quedan en ~/.config/windowtabs)."
