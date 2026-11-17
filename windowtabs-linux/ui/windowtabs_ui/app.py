"""Controlador: junta la bandeja, las barras, el puente D-Bus y los diálogos."""
import os
import shutil
import sys

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import settings as store
from .bar import BarWindow
from .bridge import CMD_SHORTCUT, Bridge, KWinClient, fallback_js
from .dialogs import CreateGroupDialog, SettingsDialog


class Controller(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.settings = store.load()
        self.state = {"groups": [], "windows": []}
        self.bars = {}
        self.dialog = None
        self.kwin = KWinClient()
        self.bridge = Bridge(lambda: self.settings)
        self.bridge.stateChanged.connect(self.on_state)
        self.bridge.fatal.connect(self.on_fatal)
        self._build_tray()

    def exec_cmd(self) -> str:
        return shutil.which("windowtabs-ui") or f"{sys.executable} -m windowtabs_ui"

    # ---------- arranque ----------
    def start(self):
        self.bridge.start()
        # pedirle al motor que mande el estado ahora mismo
        self.send({"op": "resync"})

    def on_fatal(self, msg: str):
        QMessageBox.warning(None, "WindowTabs", msg)
        self.app.quit()

    # ---------- bandeja ----------
    def _build_tray(self):
        self.tray = QSystemTrayIcon(QIcon.fromTheme("window-duplicate"), self)
        self.tray.setToolTip("WindowTabs Linux")
        menu = QMenu()
        a_group = QAction("Crear grupo…", menu)
        a_group.triggered.connect(self.create_group)
        a_set = QAction("Configuración…", menu)
        a_set.triggered.connect(self.open_settings)
        a_quit = QAction("Salir", menu)
        a_quit.triggered.connect(self.app.quit)
        menu.addAction(a_group)
        menu.addAction(a_set)
        menu.addSeparator()
        menu.addAction(a_quit)
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.open_settings() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    # ---------- estado desde KWin ----------
    def on_state(self, state: dict):
        self.state = state
        free = [w for w in state.get("windows", []) if w.get("group") is None]
        seen = set()
        for g in state.get("groups", []):
            gid = g["id"]
            seen.add(gid)
            bar = self.bars.get(gid)
            if bar is None:
                bar = BarWindow(gid, self.settings)
                bar.activateRequested.connect(lambda i: self.send({"op": "activate", "id": i}))
                bar.closeRequested.connect(lambda i: self.send({"op": "close", "id": i}))
                bar.ungroupRequested.connect(lambda i: self.send({"op": "ungroup", "id": i}))
                bar.reorderRequested.connect(lambda i, n: self.send({"op": "reorder", "id": i, "index": n}))
                bar.joinRequested.connect(lambda i, t: self.send({"op": "join", "id": i, "target": t}))
                bar.uiSettingChanged.connect(self.on_ui_setting)
                self.bars[gid] = bar
            bar.set_model(g["tabs"], g["current"], free, bool(g.get("overlay", False)))
            if g["visible"]:
                if not bar.isVisible():
                    bar.show()
            else:
                bar.hide()
        for gid in list(self.bars):
            if gid not in seen:
                self.bars.pop(gid).close()

    def on_ui_setting(self, key: str, value: int, final: bool):
        """Ajustes que se cambian arrastrando en la barra (ancho de pestañas, posición)."""
        if self.settings.get(key) != value:
            self.settings = {**self.settings, key: value}
            for bar in self.bars.values():
                bar.apply_settings(self.settings)
        if final:
            store.save(self.settings)

    # ---------- comandos hacia KWin ----------
    def send(self, cmd: dict):
        self.bridge.queue(cmd)
        if self.kwin.invoke_shortcut(CMD_SHORTCUT):
            return
        # plan B para lo más básico
        js = fallback_js(cmd)
        if js:
            self.bridge.drop_last()
            self.kwin.run_script_text(js)

    # ---------- diálogos ----------
    def create_group(self):
        dlg = CreateGroupDialog(self.state.get("windows", []))
        if dlg.exec() == CreateGroupDialog.Accepted:
            self.send({"op": "group", "ids": dlg.chosen()})

    def open_settings(self):
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        self.dialog = SettingsDialog(self.settings, self.state.get("windows", []), self.exec_cmd())
        self.dialog.applied.connect(self.apply_settings)
        self.dialog.finished.connect(lambda *_: setattr(self, "dialog", None))
        self.dialog.show()

    def apply_settings(self, new: dict, autostart: bool):
        self.settings = {**self.settings, **new}
        store.save(self.settings)
        store.set_autostart(autostart, self.exec_cmd())
        for bar in self.bars.values():
            bar.apply_settings(self.settings)
        self.send({"op": "resync"})


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORMTHEME", "kde")
    app = QApplication(sys.argv)
    app.setApplicationName("WindowTabs Linux")
    app.setDesktopFileName("windowtabs-bar")   # KWin reconoce las barras por este nombre
    app.setQuitOnLastWindowClosed(False)
    ctl = Controller(app)
    ctl.start()
    code = app.exec()
    ctl.bridge.stop()
    return code
