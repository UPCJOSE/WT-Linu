"""Comunicación con KWin por D-Bus (con jeepney, sin dependencias de GLib).

- Servicio org.windowtabs.Bar: el script de KWin le manda el estado
  (update) y le pide los comandos pendientes (popCommands).
- Cliente: la interfaz le avisa al script que hay comandos, invocando un
  atajo global de KWin; si eso falla, usa un script de un solo uso.
"""
import json
import os
import tempfile
import threading

from jeepney import DBusAddress, HeaderFields, MessageType, new_error, new_method_call, new_method_return
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import Proxy, open_dbus_connection
from PySide6.QtCore import QObject, QTimer, Signal

SERVICE = "org.windowtabs.Bar"
PATH = "/Bar"
IFACE = "org.windowtabs.Bar"
CMD_SHORTCUT = "WindowTabs: Comando de la interfaz"


class Bridge(QObject):
    stateChanged = Signal(dict)
    fatal = Signal(str)

    def __init__(self, get_settings, parent=None):
        super().__init__(parent)
        self._get_settings = get_settings
        self._cmds = []
        self._lock = threading.Lock()
        self._running = False
        self._thread = None

    # ---- servidor ----
    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def queue(self, cmd: dict):
        with self._lock:
            self._cmds.append(cmd)

    def drop_last(self):
        with self._lock:
            if self._cmds:
                self._cmds.pop()

    def _take(self) -> str:
        with self._lock:
            out, self._cmds = self._cmds, []
        return json.dumps(out)

    def _serve(self):
        try:
            conn = open_dbus_connection(bus="SESSION")
            reply = Proxy(message_bus, conn).RequestName(SERVICE, 4)  # 4 = no encolar
            if reply[0] not in (1, 4):
                self.fatal.emit("Ya hay otra copia de WindowTabs UI abierta.")
                return
        except Exception as e:  # noqa: BLE001
            self.fatal.emit(f"No se pudo conectar al bus de sesión: {e}")
            return
        while self._running:
            try:
                msg = conn.receive(timeout=1.0)
            except TimeoutError:
                continue
            except Exception:  # noqa: BLE001
                break
            h = msg.header
            if h.message_type != MessageType.method_call:
                continue
            member = h.fields.get(HeaderFields.member)
            try:
                if member == "update":
                    try:
                        self.stateChanged.emit(json.loads(msg.body[0]))
                    except ValueError:
                        pass
                    out = json.dumps(self._get_settings())
                    conn.send_message(new_method_return(msg, "s", (out,)))
                elif member == "popCommands":
                    conn.send_message(new_method_return(msg, "s", (self._take(),)))
                else:
                    conn.send_message(new_error(
                        msg, "org.freedesktop.DBus.Error.UnknownMethod", "s", (f"No existe {member}",)))
            except Exception:  # noqa: BLE001
                pass
        conn.close()


class KWinClient:
    """Llamadas hacia KWin."""

    def __init__(self):
        self._timers = []

    def _call(self, address, method, signature="", body=()):
        conn = open_dbus_connection(bus="SESSION")
        try:
            msg = new_method_call(address, method, signature, body)
            return conn.send_and_get_reply(msg, timeout=3)
        finally:
            conn.close()

    def invoke_shortcut(self, name: str) -> bool:
        addr = DBusAddress("/component/kwin", bus_name="org.kde.kglobalaccel",
                           interface="org.kde.kglobalaccel.Component")
        for sig, body in (("s", (name,)), ("ss", (name, ""))):
            try:
                r = self._call(addr, "invokeShortcut", sig, body)
                if r.header.message_type != MessageType.error:
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def run_script_text(self, js: str) -> bool:
        """Plan B: carga y ejecuta un script de un solo uso en KWin."""
        try:
            fd, path = tempfile.mkstemp(prefix="wt-cmd-", suffix=".js")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(js)
            name = os.path.basename(path)
            scripting = DBusAddress("/Scripting", bus_name="org.kde.KWin",
                                    interface="org.kde.kwin.Scripting")
            r = self._call(scripting, "loadScript", "ss", (path, name))
            if r.header.message_type == MessageType.error:
                return False
            sid = r.body[0]
            script = DBusAddress(f"/Scripting/Script{sid}", bus_name="org.kde.KWin",
                                 interface="org.kde.kwin.Script")
            self._call(script, "run")
            self._schedule_unload(name, path)
            return True
        except Exception:  # noqa: BLE001
            return False

    def _schedule_unload(self, name, path):
        def unload():
            try:
                scripting = DBusAddress("/Scripting", bus_name="org.kde.KWin",
                                        interface="org.kde.kwin.Scripting")
                self._call(scripting, "unloadScript", "s", (name,))
            except Exception:  # noqa: BLE001
                pass
            try:
                os.unlink(path)
            except OSError:
                pass
        QTimer.singleShot(1500, unload)


def fallback_js(cmd: dict):
    """Script de un solo uso para las acciones que no necesitan el estado del motor."""
    wid = json.dumps(cmd.get("id", ""))
    body = {
        "activate": "if (w.minimized) w.minimized = false; workspace.activeWindow = w;",
        "close": "w.closeWindow();",
    }.get(cmd.get("op"))
    if not body:
        return None
    return (f"var id = {wid};\nworkspace.windowList().forEach(function (w) {{\n"
            f"  if (String(w.internalId) === id) {{ {body} }}\n}});\n")
