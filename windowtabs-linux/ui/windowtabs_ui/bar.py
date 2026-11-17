"""Barra de pestañas de un grupo (una ventana sin bordes que KWin coloca)."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen, QPalette, QRegion
from PySide6.QtWidgets import QMenu, QToolTip, QWidget

PAD = 10          # margen interno de cada pestaña
ICON = 16
CLOSE = 16
GAP = 2
PLUS_W = 30
GRIP_W = 10       # agarre para deslizar la tira de pestañas (solo sobre el titlebar)
HANDLE_W = 6      # zona para cambiar el ancho de las pestañas
MIN_TAB = 70
MAX_TAB = 600
QWIDGETSIZE_MAX = 16777215


def themed_icon(name: str) -> QIcon:
    for candidate in (name, name.lower(), name.split(".")[-1].lower()):
        if candidate and QIcon.hasThemeIcon(candidate):
            return QIcon.fromTheme(candidate)
    return QIcon.fromTheme("application-x-executable")


def mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        round(a.red() * (1 - t) + b.red() * t),
        round(a.green() * (1 - t) + b.green() * t),
        round(a.blue() * (1 - t) + b.blue() * t),
        round(a.alpha() * (1 - t) + b.alpha() * t),
    )


class Colors:
    def __init__(self, palette: QPalette, theme: str):
        accent = palette.color(QPalette.Highlight)
        if theme == "dark":
            self.bg, self.text = QColor("#1f2225"), QColor("#eff0f1")
        elif theme == "light":
            self.bg, self.text = QColor("#e4e6e8"), QColor("#232629")
        else:
            self.bg = palette.color(QPalette.Window)
            self.text = palette.color(QPalette.WindowText)
            self.bg = mix(self.bg, QColor("black"), 0.08)
        dark = self.bg.lightness() < 128
        self.active = mix(self.bg, QColor("white" if dark else "white"), 0.16 if dark else 0.7)
        self.hover = mix(self.bg, self.text, 0.08)
        self.muted = mix(self.text, self.bg, 0.4)
        self.accent = accent
        self.sep = mix(self.bg, self.text, 0.14)


class BarWindow(QWidget):
    activateRequested = Signal(str)
    closeRequested = Signal(str)
    ungroupRequested = Signal(str)
    reorderRequested = Signal(str, int)
    joinRequested = Signal(str, str)      # (ventana a unir, ventana visible del grupo)
    uiSettingChanged = Signal(str, int, bool)   # (ajuste, valor, ¿ya soltó el ratón?)

    def __init__(self, gid: int, settings: dict):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.gid = gid
        self.settings = settings
        self.tabs = []
        self.current = ""
        self.free = []
        self._hover = -1
        self._hover_close = False
        self._plus_hover = False
        self._press = None        # (índice, posición)
        self._drag = None         # {"idx":, "x":, "dx":}
        self._resize = None       # {"x":, "w":}  cambiando el ancho de las pestañas
        self._grip = None         # {"x":, "off":} deslizando la tira
        self._grip_hover = False
        self._handle_hover = False
        self.overlay = False      # True = la barra está encima del titlebar de la ventana
        self._mask_key = None
        self.setWindowTitle(f"WindowTabs#{gid}")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setMinimumWidth(100)
        self.apply_settings(settings)

    # ---------- datos ----------
    def apply_settings(self, s: dict):
        self.settings = s
        self._apply_constraints()
        self._update_mask()
        self.update()

    def _apply_constraints(self):
        # sobre el titlebar el alto lo manda KWin (el del titlebar); arriba/abajo es fijo
        if self.overlay:
            self.setMinimumHeight(14)
            self.setMaximumHeight(QWIDGETSIZE_MAX)
        else:
            self.setFixedHeight(int(self.settings.get("barHeight", 32)))

    def set_model(self, tabs, current, free, overlay=False):
        self.tabs, self.current, self.free = tabs, current, free
        self._hover = -1
        self._drag = None
        if overlay != self.overlay:
            self.overlay = overlay
            self._apply_constraints()
        self._update_mask()
        self.update()

    def _update_mask(self):
        """Sobre el titlebar solo la tira de pestañas recibe clics; el resto del
        titlebar sigue siendo de la ventana (mover, doble clic para maximizar...)."""
        if self.overlay and self.tabs and self.width() > 0 and self.height() > 0:
            left = max(0, int(self._offset()))
            right = min(self.width(), int(self._plus_rect().right()) + 3)
            key = (left, right, self.height())
            if key != self._mask_key:
                self._mask_key = key
                self.setMask(QRegion(left, 0, max(1, right - left), self.height()))
        elif self._mask_key is not None:
            self._mask_key = None
            self.clearMask()

    def resizeEvent(self, e):
        self._update_mask()
        super().resizeEvent(e)

    # ---------- geometría ----------
    def _top(self) -> bool:
        return self.overlay or self.settings.get("barPosition", "top") != "bottom"

    def _offset(self) -> float:
        """Cuánto se ha deslizado la tira hacia la derecha (solo sobre el titlebar)."""
        if not self.overlay:
            return 0.0
        return float(max(0, min(int(self.settings.get("tabOffset", 0)), max(0, self.width() - 150))))

    def _start_x(self) -> float:
        return self._offset() + (GRIP_W + 4 if self.overlay else 4)

    def _grip_rect(self):
        return QRectF(self._offset() + 1, 2, GRIP_W, max(1, self.height() - 4))

    def _tab_rects(self):
        n = len(self.tabs)
        if n == 0:
            return []
        x0 = self._start_x()
        avail = self.width() - x0 - PLUS_W - 10
        w = min(float(self.settings.get("tabMaxWidth", 220)), (avail - GAP * (n - 1)) / n)
        w = max(w, 54.0)
        if self.overlay:
            h, y = self.height() - 4.0, 2.0
        else:
            h, y = self.height() - 6.0, (5.0 if self._top() else 1.0)
        return [QRectF(x0 + i * (w + GAP), y, w, h) for i in range(n)]

    def _plus_rect(self):
        rects = self._tab_rects()
        x = (rects[-1].right() + 6) if rects else self._start_x() + 2
        return QRectF(x, (self.height() - 24) / 2, 24, 24)

    def _handle_rect(self):
        """Borde derecho de la última pestaña: arrastrarlo cambia el ancho de todas."""
        rects = self._tab_rects()
        if not rects:
            return QRectF()
        r = rects[-1]
        return QRectF(r.right() - 1, r.top(), HANDLE_W, r.height())

    def _close_rect(self, r: QRectF):
        return QRectF(r.right() - PAD - CLOSE + 4, r.center().y() - CLOSE / 2, CLOSE, CLOSE)

    def _show_close(self, i: int, tab_id: str) -> bool:
        mode = self.settings.get("closeButton", "hover")
        if mode == "never":
            return False
        if mode == "always":
            return True
        return i == self._hover or tab_id == self.current

    # ---------- dibujo ----------
    def paintEvent(self, _):
        c = Colors(self.palette(), self.settings.get("theme", "system"))
        r = float(self.settings.get("cornerRadius", 8))
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.overlay:
            # fondo de la barra, con las esquinas redondeadas del lado de afuera
            full = QRectF(0, 0, self.width(), self.height())
            path = QPainterPath()
            path.addRoundedRect(full, r, r)
            cover = QRectF(0, self.height() / 2, self.width(), self.height() / 2) if self._top() \
                else QRectF(0, 0, self.width(), self.height() / 2)
            path.addRect(cover)
            p.fillPath(path.simplified(), c.bg)
        else:
            self._paint_grip(p, c, r)

        font = QFont(self.font())
        font.setPointSizeF(max(8.5, font.pointSizeF()))
        p.setFont(font)
        fm = QFontMetrics(font)
        rects = self._tab_rects()
        order = list(range(len(rects)))
        if self._drag:
            order.remove(self._drag["idx"])
            order.append(self._drag["idx"])
        for i in order:
            tab, rect = self.tabs[i], QRectF(rects[i])
            if self._drag and i == self._drag["idx"]:
                rect.moveLeft(self._drag["x"])
            active = tab["id"] == self.current
            hovered = i == self._hover
            fill = c.active if active else (c.hover if hovered else None)
            if self.overlay:
                # sobre el titlebar las pestañas son opacas: tapan el título de la ventana
                fill = c.active if active else (mix(c.bg, c.text, 0.12) if hovered else c.bg)
            if fill is not None:
                tp = QPainterPath()
                tp.addRoundedRect(rect, r - 1, r - 1)
                p.fillPath(tp, fill)
                if self.overlay:
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(c.sep, 1))
                    p.drawPath(tp)
            if active:
                p.setPen(Qt.NoPen)
                p.setBrush(c.accent)
                ay = rect.top() + 1 if self._top() else rect.bottom() - 3
                p.drawRoundedRect(QRectF(rect.left() + r, ay, rect.width() - 2 * r, 2), 1, 1)
            x = rect.left() + PAD
            if self.settings.get("showIcons", True):
                icon = themed_icon(tab.get("icon", ""))
                icon.paint(p, int(x), int(rect.center().y() - ICON / 2), ICON, ICON)
                x += ICON + 7
            show_close = self._show_close(i, tab["id"])
            right = rect.right() - PAD - (CLOSE - 2 if show_close else 0)
            p.setPen(c.text if active or hovered else c.muted)
            text = fm.elidedText(tab.get("title", ""), Qt.ElideRight, max(0, int(right - x)))
            p.drawText(QRectF(x, rect.top(), max(0.0, right - x), rect.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, text)
            if show_close:
                cr = self._close_rect(rect)
                if hovered and self._hover_close:
                    p.setPen(Qt.NoPen)
                    p.setBrush(mix(c.bg, c.text, 0.2))
                    p.drawEllipse(cr)
                pen = QPen(c.text if (hovered and self._hover_close) else c.muted, 1.4)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                m = 4.6
                p.drawLine(QPointF(cr.center().x() - m, cr.center().y() - m), QPointF(cr.center().x() + m, cr.center().y() + m))
                p.drawLine(QPointF(cr.center().x() - m, cr.center().y() + m), QPointF(cr.center().x() + m, cr.center().y() - m))
            # separador fino entre pestañas inactivas
            if not self.overlay and i + 1 < len(rects) and not active and not hovered and not self._drag \
                    and self.tabs[i + 1]["id"] != self.current and i + 1 != self._hover:
                p.setPen(QPen(c.sep, 1))
                p.drawLine(QPointF(rect.right() + GAP / 2, rect.top() + 7), QPointF(rect.right() + GAP / 2, rect.bottom() - 7))
        # botón "+"
        pr = self._plus_rect()
        if self._plus_hover or self.overlay:
            pp = QPainterPath()
            pp.addRoundedRect(pr, 6, 6)
            p.fillPath(pp, c.hover if self._plus_hover else c.bg)
        p.setPen(QPen(c.text if self._plus_hover else c.muted, 1.6))
        cx, cy = pr.center().x(), pr.center().y()
        p.drawLine(QPointF(cx - 5, cy), QPointF(cx + 5, cy))
        p.drawLine(QPointF(cx, cy - 5), QPointF(cx, cy + 5))
        # tirador del ancho: se ve al pasar el cursor o mientras se arrastra
        if rects and (self._handle_hover or self._resize):
            hr = self._handle_rect()
            p.setPen(Qt.NoPen)
            p.setBrush(c.accent)
            p.drawRoundedRect(QRectF(hr.center().x() - 1.5, hr.top() + 4, 3, max(2.0, hr.height() - 8)), 1.5, 1.5)
        p.end()

    def _paint_grip(self, p, c, r):
        g = self._grip_rect()
        gp = QPainterPath()
        gp.addRoundedRect(g, min(r, 5), min(r, 5))
        p.fillPath(gp, mix(c.bg, c.text, 0.12) if (self._grip_hover or self._grip) else c.bg)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(c.sep, 1))
        p.drawPath(gp)
        p.setPen(Qt.NoPen)
        p.setBrush(c.text if (self._grip_hover or self._grip) else c.muted)
        cx, cy = g.center().x(), g.center().y()
        for dy in (-6, 0, 6):
            p.drawEllipse(QPointF(cx, cy + dy), 1.3, 1.3)

    # ---------- ratón ----------
    def _index_at(self, pos):
        for i, r in enumerate(self._tab_rects()):
            if r.adjusted(0, -5, GAP, 5).contains(pos):
                return i
        return -1

    def _over_handle(self, pos) -> bool:
        return bool(self.tabs) and self._handle_rect().adjusted(-2, -3, 2, 3).contains(pos)

    def _over_grip(self, pos) -> bool:
        return self.overlay and self._grip_rect().adjusted(0, -3, 2, 3).contains(pos)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self._resize:
            n = max(1, len(self.tabs))
            w = self._resize["w"] + (pos.x() - self._resize["x"]) / n
            self.uiSettingChanged.emit("tabMaxWidth", int(max(MIN_TAB, min(MAX_TAB, w))), False)
            return
        if self._grip:
            off = self._grip["off"] + (pos.x() - self._grip["x"])
            self.uiSettingChanged.emit("tabOffset", int(max(0, min(off, max(0, self.width() - 150)))), False)
            return
        if self._press and e.buttons() & Qt.LeftButton and len(self.tabs) > 1:
            idx, start = self._press
            if self._drag is None and abs(pos.x() - start.x()) > 8:
                r0 = self._tab_rects()[idx]
                self._drag = {"idx": idx, "x": r0.left(), "dx": start.x() - r0.left()}
            if self._drag:
                self._drag["x"] = pos.x() - self._drag["dx"]
                self.update()
            return
        i = self._index_at(pos)
        over_close = False
        if i >= 0:
            r = self._tab_rects()[i]
            over_close = self._show_close(i, self.tabs[i]["id"]) and self._close_rect(r).adjusted(-3, -3, 3, 3).contains(pos)
            QToolTip.showText(e.globalPosition().toPoint(), self.tabs[i].get("title", ""), self)
        plus = self._plus_rect().contains(pos)
        handle, grip = self._over_handle(pos), self._over_grip(pos)
        if handle:
            i, over_close = -1, False
            QToolTip.hideText()
        self.setCursor(Qt.SizeHorCursor if handle else (Qt.SizeAllCursor if grip else Qt.ArrowCursor))
        state = (i, over_close, plus, handle, grip)
        if state != (self._hover, self._hover_close, self._plus_hover, self._handle_hover, self._grip_hover):
            self._hover, self._hover_close, self._plus_hover, self._handle_hover, self._grip_hover = state
            self.update()

    def leaveEvent(self, _):
        self._hover, self._hover_close, self._plus_hover = -1, False, False
        self._handle_hover = self._grip_hover = False
        self.unsetCursor()
        self.update()

    def wheelEvent(self, e):
        # Ctrl + rueda = pestañas más anchas / más angostas
        if e.modifiers() & Qt.ControlModifier and self.tabs:
            cur = self._tab_rects()[0].width()
            step = 12 if e.angleDelta().y() > 0 else -12
            self.uiSettingChanged.emit("tabMaxWidth", int(max(MIN_TAB, min(MAX_TAB, cur + step))), True)
            e.accept()
        else:
            e.ignore()

    def mousePressEvent(self, e):
        pos = e.position()
        i = self._index_at(pos)
        if e.button() == Qt.LeftButton:
            if self._over_handle(pos):
                self._resize = {"x": pos.x(), "w": self._tab_rects()[0].width()}
                self.update()
            elif self._over_grip(pos):
                self._grip = {"x": pos.x(), "off": self._offset()}
                self.update()
            elif self._plus_rect().contains(pos):
                self._plus_menu(e.globalPosition().toPoint())
            elif i >= 0:
                tab = self.tabs[i]
                r = self._tab_rects()[i]
                if self._show_close(i, tab["id"]) and self._close_rect(r).adjusted(-3, -3, 3, 3).contains(pos):
                    self.closeRequested.emit(tab["id"])
                else:
                    self._press = (i, pos)
                    if tab["id"] != self.current:
                        self.activateRequested.emit(tab["id"])
        elif e.button() == Qt.MiddleButton and i >= 0:
            self.closeRequested.emit(self.tabs[i]["id"])
        elif e.button() == Qt.RightButton and i >= 0:
            self._tab_menu(i, e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e):
        if self._resize or self._grip:
            # guardar el valor final (sale de lo que ya se ve en pantalla)
            if self._resize and self.tabs:
                self.uiSettingChanged.emit("tabMaxWidth", int(self.settings.get("tabMaxWidth", 220)), True)
            if self._grip:
                self.uiSettingChanged.emit("tabOffset", int(self.settings.get("tabOffset", 0)), True)
            self._resize = self._grip = None
            self.update()
            return
        if self._drag is not None and self._press:
            idx = self._press[0]
            centre = self._drag["x"] + self._tab_rects()[idx].width() / 2
            target = 0
            for j, r in enumerate(self._tab_rects()):
                if centre > r.center().x():
                    target = j + (0 if j < idx else 0)
            target = sum(1 for j, r in enumerate(self._tab_rects()) if j != idx and centre > r.center().x())
            if target != idx:
                self.reorderRequested.emit(self.tabs[idx]["id"], target)
        self._press = None
        self._drag = None
        self.update()

    # ---------- menús ----------
    def _tab_menu(self, i: int, global_pos):
        tab = self.tabs[i]
        m = QMenu(self)
        a_close = m.addAction("Cerrar ventana")
        a_out = m.addAction("Sacar del grupo")
        chosen = m.exec(global_pos)
        if chosen is a_close:
            self.closeRequested.emit(tab["id"])
        elif chosen is a_out:
            self.ungroupRequested.emit(tab["id"])

    def _plus_menu(self, global_pos):
        m = QMenu(self)
        head = m.addAction("Agregar ventana al grupo")
        head.setEnabled(False)
        m.addSeparator()
        fm = QFontMetrics(m.font())
        actions = {}
        for w in self.free:
            a = m.addAction(themed_icon(w.get("icon", "")), fm.elidedText(w.get("title", ""), Qt.ElideRight, 360))
            actions[a] = w["id"]
        if not actions:
            none = m.addAction("No hay otras ventanas sueltas")
            none.setEnabled(False)
        chosen = m.exec(global_pos)
        if chosen in actions:
            self.joinRequested.emit(actions[chosen], self.current)
