"""Ventana de configuración y diálogo para crear grupos."""
from PySide6.QtCore import Qt, QProcess, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QVBoxLayout, QWidget, QHeaderView,
)

from . import settings as store
from .bar import themed_icon

SHORTCUTS = [
    ("Siguiente ventana del grupo", "Ctrl+Alt+Derecha"),
    ("Ventana anterior del grupo", "Ctrl+Alt+Izquierda"),
    ("Marcar / unir ventana", "Meta+G"),
    ("Sacar ventana del grupo", "Meta+Shift+G"),
    ("Agrupar todas las de esta app", "Meta+Ctrl+G"),
    ("Activar/desactivar agrupar automático", "Meta+Alt+G"),
]


class SettingsDialog(QDialog):
    applied = Signal(dict, bool)      # (ajustes, iniciar con la sesión)

    def __init__(self, current: dict, windows: list, exec_cmd: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WindowTabs Linux — Configuración")
        self.setMinimumSize(560, 520)
        self._windows = windows
        self._exec_cmd = exec_cmd
        tabs = QTabWidget()
        tabs.addTab(self._general_page(current), "General")
        tabs.addTab(self._look_page(current), "Apariencia")
        tabs.addTab(self._keys_page(), "Atajos")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).clicked.connect(lambda: (self._apply(), self.accept()))
        buttons.button(QDialogButtonBox.Apply).clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(buttons)

    # ---------- páginas ----------
    def _general_page(self, s):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.auto = QCheckBox("Agrupar automáticamente las apps de la lista")
        self.auto.setChecked(s["autoGroupEnabled"])
        lay.addWidget(self.auto)
        lay.addWidget(QLabel("Apps que se agrupan solas (clase de ventana):"))
        self.apps = QListWidget()
        for a in s["autoGroupApps"]:
            self.apps.addItem(a)
        lay.addWidget(self.apps, 1)
        row = QHBoxLayout()
        self.app_edit = QLineEdit()
        self.app_edit.setPlaceholderText("ej: firefox, kate, org.kde.dolphin")
        add = QPushButton("Agregar")
        add.clicked.connect(self._add_app)
        self.app_edit.returnPressed.connect(self._add_app)
        pick = QPushButton("Elegir de las abiertas…")
        pick.clicked.connect(self._pick_app)
        rem = QPushButton("Quitar")
        rem.clicked.connect(lambda: [self.apps.takeItem(self.apps.row(i)) for i in self.apps.selectedItems()])
        for x in (self.app_edit, add, pick, rem):
            row.addWidget(x)
        lay.addLayout(row)
        self.hide_inactive = QCheckBox("Minimizar la ventana anterior al cambiar de pestaña")
        self.hide_inactive.setChecked(s["hideInactive"])
        self.osd = QCheckBox("Mostrar avisos en pantalla")
        self.osd.setChecked(s["showOSD"])
        self.autostart = QCheckBox("Iniciar WindowTabs al abrir sesión")
        self.autostart.setChecked(store.autostart_enabled())
        for x in (self.hide_inactive, self.osd, self.autostart):
            lay.addWidget(x)
        return w

    def _look_page(self, s):
        w = QWidget()
        form = QFormLayout(w)
        self.pos = QComboBox()
        self.pos.addItem("Sobre la barra de título (como WindowTabs de Windows)", "titlebar")
        self.pos.addItem("Arriba de la ventana", "top")
        self.pos.addItem("Abajo de la ventana", "bottom")
        self.pos.setCurrentIndex(self.pos.findData(s["barPosition"]))
        self.height_ = QSpinBox(); self.height_.setRange(24, 56); self.height_.setSuffix(" px")
        self.height_.setValue(s["barHeight"])
        self.maxw = QSpinBox(); self.maxw.setRange(70, 600); self.maxw.setSuffix(" px")
        self.maxw.setValue(s["tabMaxWidth"])
        self.inset_l = QSpinBox(); self.inset_l.setRange(0, 400); self.inset_l.setSuffix(" px")
        self.inset_l.setValue(s["insetLeft"])
        self.inset_r = QSpinBox(); self.inset_r.setRange(0, 400); self.inset_r.setSuffix(" px")
        self.inset_r.setValue(s["insetRight"])
        self.radius = QSpinBox(); self.radius.setRange(0, 16); self.radius.setSuffix(" px")
        self.radius.setValue(s["cornerRadius"])
        self.icons = QCheckBox("Mostrar el icono de cada app")
        self.icons.setChecked(s["showIcons"])
        self.close_btn = QComboBox()
        for label, key in (("Al pasar el cursor", "hover"), ("Siempre", "always"), ("Nunca", "never")):
            self.close_btn.addItem(label, key)
        self.close_btn.setCurrentIndex(self.close_btn.findData(s["closeButton"]))
        self.theme = QComboBox()
        for label, key in (("Seguir al sistema", "system"), ("Claro", "light"), ("Oscuro", "dark")):
            self.theme.addItem(label, key)
        self.theme.setCurrentIndex(self.theme.findData(s["theme"]))
        form.addRow("Posición de la barra", self.pos)
        form.addRow("Alto de la barra (arriba/abajo)", self.height_)
        form.addRow("Ancho de las pestañas", self.maxw)
        form.addRow("Margen izquierdo del título", self.inset_l)
        form.addRow("Margen derecho (botones de la ventana)", self.inset_r)
        form.addRow("Redondeo de esquinas", self.radius)
        form.addRow("Botón de cerrar", self.close_btn)
        form.addRow("Tema", self.theme)
        form.addRow("", self.icons)
        hint = QLabel("Tip: también puedes cambiar el ancho arrastrando el borde derecho de la última "
                      "pestaña (o con Ctrl + rueda del ratón), y deslizar toda la tira con el agarre "
                      "de la izquierda.")
        hint.setWordWrap(True)
        form.addRow(hint)

        def toggle(*_):
            on = self.pos.currentData() == "titlebar"
            self.inset_l.setEnabled(on)
            self.inset_r.setEnabled(on)
            self.height_.setEnabled(not on)
        self.pos.currentIndexChanged.connect(toggle)
        toggle()
        return w

    def _keys_page(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(QLabel("Estos son los atajos por defecto. Se cambian en los ajustes de KDE:"))
        t = QTableWidget(len(SHORTCUTS), 2)
        t.setHorizontalHeaderLabels(["Acción", "Atajo por defecto"])
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        for i, (a, k) in enumerate(SHORTCUTS):
            t.setItem(i, 0, QTableWidgetItem(a))
            t.setItem(i, 1, QTableWidgetItem(k))
        lay.addWidget(t, 1)
        b = QPushButton("Abrir atajos de teclado de KDE…")
        b.clicked.connect(lambda: QProcess.startDetached("systemsettings", ["kcm_keys"]))
        lay.addWidget(b)
        lay.addWidget(QLabel("Ahí busca «WindowTabs» para elegir la combinación que quieras."))
        return w

    # ---------- acciones ----------
    def _add_app(self):
        for part in self.app_edit.text().lower().replace(";", ",").split(","):
            part = part.strip()
            if part and not self.apps.findItems(part, Qt.MatchExactly):
                self.apps.addItem(part)
        self.app_edit.clear()

    def _pick_app(self):
        seen = {}
        for w in self._windows:
            if w.get("cls") and w["cls"] not in seen:
                seen[w["cls"]] = w
        m = QMenu(self)
        acts = {}
        for cls, w in sorted(seen.items()):
            acts[m.addAction(themed_icon(w.get("icon", "")), cls)] = cls
        if not acts:
            m.addAction("No hay ventanas abiertas").setEnabled(False)
        chosen = m.exec(self.mapToGlobal(self.app_edit.pos()))
        if chosen in acts and not self.apps.findItems(acts[chosen], Qt.MatchExactly):
            self.apps.addItem(acts[chosen])

    def collect(self) -> dict:
        return {
            "autoGroupEnabled": self.auto.isChecked(),
            "autoGroupApps": [self.apps.item(i).text() for i in range(self.apps.count())],
            "hideInactive": self.hide_inactive.isChecked(),
            "showOSD": self.osd.isChecked(),
            "barHeight": self.height_.value(),
            "barPosition": self.pos.currentData(),
            "insetLeft": self.inset_l.value(),
            "insetRight": self.inset_r.value(),
            "tabMaxWidth": self.maxw.value(),
            "cornerRadius": self.radius.value(),
            "showIcons": self.icons.isChecked(),
            "closeButton": self.close_btn.currentData(),
            "theme": self.theme.currentData(),
        }

    def _apply(self):
        self.applied.emit(self.collect(), self.autostart.isChecked())


class CreateGroupDialog(QDialog):
    def __init__(self, windows: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Crear grupo")
        self.setMinimumSize(420, 360)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Marca las ventanas que quieres juntar en un grupo (mínimo 2):"))
        self.list = QListWidget()
        for w in windows:
            it = QListWidgetItem(themed_icon(w.get("icon", "")), w.get("title", ""))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, w["id"])
            self.list.addItem(it)
        lay.addWidget(self.list, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)
        self.list.itemChanged.connect(self._check)
        self._check()

    def _check(self, *_):
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(len(self.chosen()) >= 2)

    def chosen(self) -> list:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out
