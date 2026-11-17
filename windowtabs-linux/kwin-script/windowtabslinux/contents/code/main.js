// WindowTabs Linux - motor en KWin (Plasma 6, Wayland y X11)
// Se encarga de: grupos, misma posicion, cambio con teclas y de colocar
// las barras de pestañas que dibuja la app "windowtabs-ui".
"use strict";

var UI_SERVICE = "org.windowtabs.Bar";
var UI_PATH = "/Bar";
var UI_IFACE = "org.windowtabs.Bar";
var BAR_CLASS = "windowtabs-bar";

var groups = [];        // { id, members: [ventana], current: ventana }
var nextGroupId = 1;
var tracked = [];       // ventanas con señales ya conectadas
var pending = null;     // ventana marcada con Meta+G
var autoOverride = null;
var syncing = false;
var lastState = "";

var settings = {
    autoGroupEnabled: true,
    autoGroupApps: String(readConfig("autoGroupApps", "")).toLowerCase()
        .split(/[,;\s]+/).filter(function (s) { return s.length > 0; }),
    hideInactive: readConfig("hideInactive", false),
    showOSD: readConfig("showOSD", true),
    barHeight: 32,
    barPosition: "titlebar",   // titlebar | top | bottom
    insetLeft: 30,             // espacio libre a la izquierda del titlebar (icono de la app)
    insetRight: 96             // espacio libre a la derecha (botones minimizar/maximizar/cerrar)
};

// ---------- utilidades ----------

function osd(text) {
    if (!settings.showOSD) return;
    callDBus("org.kde.plasmashell", "/org/kde/osdService",
             "org.kde.osdService", "showText", "window-duplicate", text);
}

function cloneRect(r) {
    return { x: r.x, y: r.y, width: r.width, height: r.height };
}

function wid(w) { return String(w.internalId); }

function className(w) { return String(w.resourceClass).toLowerCase(); }

function isBar(w) {
    return !!w && className(w) === BAR_CLASS && /^WindowTabs#\d+$/.test(String(w.caption));
}

function barGroupId(w) {
    var m = /^WindowTabs#(\d+)$/.exec(String(w.caption));
    return m ? parseInt(m[1], 10) : -1;
}

function isGroupable(w) {
    return !!w && w.normalWindow && !w.transient && className(w) !== BAR_CLASS;
}

function findById(id) {
    var list = workspace.windowList();
    for (var i = 0; i < list.length; i++) {
        if (wid(list[i]) === id) return list[i];
    }
    return null;
}

function groupOf(w) {
    for (var i = 0; i < groups.length; i++) {
        if (groups[i].members.indexOf(w) !== -1) return groups[i];
    }
    return null;
}

function groupById(id) {
    for (var i = 0; i < groups.length; i++) {
        if (groups[i].id === id) return groups[i];
    }
    return null;
}

function barFor(g) {
    var list = workspace.windowList();
    for (var i = 0; i < list.length; i++) {
        if (isBar(list[i]) && barGroupId(list[i]) === g.id) return list[i];
    }
    return null;
}

function applySettings(json) {
    try {
        var o = JSON.parse(json);
        for (var k in o) settings[k] = o[k];
    } catch (e) { /* sin interfaz: se queda con los valores actuales */ }
}

function autoIsOn() {
    return autoOverride === null ? settings.autoGroupEnabled : autoOverride;
}

// ---------- geometria ----------

function setGeom(w, r) {
    if (!w || w.fullScreen) return;
    syncing = true;
    w.frameGeometry = cloneRect(r);
    syncing = false;
}

function copyGeometry(from, to) {
    if (!from || !to || from.fullScreen) return;
    setGeom(to, from.frameGeometry);
}

function areaOf(w) {
    try { return workspace.clientArea(KWin.PlacementArea, w); }
    catch (e) { return null; }
}

// alto del titlebar de la ventana (0 = no tiene, p. ej. ventanas con decoracion propia)
function titlebarHeight(w) {
    try {
        var c = w.clientGeometry, f = w.frameGeometry;
        if (!c || !f) return settings.barHeight;      // la API no lo dice: usar el alto configurado
        var h = Math.round(c.y - f.y);
        return (h >= 12 && h <= 120) ? h : 0;
    } catch (e) { return settings.barHeight; }
}

// donde va la barra de este grupo: "titlebar" (encima del titlebar), "top" o "bottom"
function posOf(g) {
    if (settings.barPosition === "bottom") return "bottom";
    if (settings.barPosition === "top") return "top";
    var cur = g.current;
    // sin titlebar no hay donde apoyar las pestañas: se ponen arriba de la ventana
    return (cur && titlebarHeight(cur) > 0) ? "titlebar" : "top";
}

// deja sitio para la barra de pestañas dentro de la pantalla (solo arriba/abajo;
// sobre el titlebar la ventana no se toca)
function reserveRoom(g) {
    var cur = g.current;
    if (!cur || cur.fullScreen) return;
    var pos = posOf(g);
    if (pos === "titlebar") return;
    var a = areaOf(cur);
    if (!a) return;
    var H = settings.barHeight;
    var r = cloneRect(cur.frameGeometry);
    var changed = false;
    if (pos === "bottom") {
        var maxBottom = a.y + a.height - H;
        if (r.y + r.height > maxBottom) { r.height = maxBottom - r.y; changed = true; }
    } else {
        var minY = a.y + H;
        if (r.y < minY) { r.height -= (minY - r.y); r.y = minY; changed = true; }
    }
    if (!changed || r.height < 100) return;
    g.members.forEach(function (m) { setGeom(m, r); });
}

function layoutBars() {
    var modeChanged = false;
    groups.forEach(function (g) {
        var bar = barFor(g);
        var cur = g.current;
        if (!bar || !cur) return;
        var pos = posOf(g);
        if (g.pos !== pos) {
            g.pos = pos;
            modeChanged = true;
            reserveRoom(g);
        }
        var r = cur.frameGeometry;
        var geom;
        if (pos === "titlebar") {
            var th = titlebarHeight(cur);
            var li = Math.max(0, settings.insetLeft), ri = Math.max(0, settings.insetRight);
            geom = { x: r.x + li, y: r.y, width: Math.max(80, r.width - li - ri), height: th };
        } else {
            var H = settings.barHeight;
            geom = { x: r.x, y: pos === "bottom" ? r.y + r.height : r.y - H, width: r.width, height: H };
        }
        syncing = true;
        bar.frameGeometry = geom;
        syncing = false;
    });
    if (modeChanged) pushState();
}

function raiseBar(g) {
    var bar = barFor(g);
    if (bar && workspace.raiseWindow) workspace.raiseWindow(bar);
}

// Capas: la barra va encima de SU ventana (sobre el titlebar). Mientras el grupo
// esta activo la barra queda "siempre encima" (asi ni el clic dentro de la ventana
// ni el orden en que KWin sube la ventana la tapan); al activar otra cosa se
// suelta, para que no flote sobre las demas ventanas.
function setAbove(bar, on) {
    try { if (bar.keepAbove !== on) bar.keepAbove = on; } catch (e) { }
}

function fixOrder(g, active) {
    var bar = barFor(g), cur = g.current;
    var so = workspace.stackingOrder;
    if (!bar || !cur || !so || !workspace.raiseWindow) return;
    var ib = so.indexOf(bar), ic = so.indexOf(cur);
    if (ib !== -1 && ic !== -1 && ib < ic) {
        // la ventana quedo por encima de su barra: subir la barra y devolver
        // arriba a la ventana activa
        workspace.raiseWindow(bar);
        if (active && !isBar(active)) workspace.raiseWindow(active);
    }
}

function syncLayers(active) {
    groups.forEach(function (g) {
        var bar = barFor(g);
        if (!bar) return;
        var on = !!active && (active === bar || groupOf(active) === g);
        setAbove(bar, on);
        if (on) raiseBar(g); else fixOrder(g, active);
    });
}

// ---------- grupos ----------

function removeFromGroup(w) {
    var g = groupOf(w);
    if (!g) return;
    g.members.splice(g.members.indexOf(w), 1);
    if (g.current === w) g.current = g.members[0] || null;
    if (g.members.length < 2) groups.splice(groups.indexOf(g), 1);
}

function addToGroup(target, w) {
    var g = groupOf(target);
    if (!g) {
        g = { id: nextGroupId++, members: [target], current: target };
        groups.push(g);
    }
    var old = groupOf(w);
    if (old === g) return g;
    if (old) removeFromGroup(w);
    g.members.push(w);
    copyGeometry(g.current || target, w);
    reserveRoom(g);
    return g;
}

function maybeAutoGroup(w) {
    if (!isGroupable(w) || !autoIsOn() || groupOf(w)) return;
    var cls = className(w);
    if (cls === "" || settings.autoGroupApps.indexOf(cls) === -1) return;
    var others = workspace.windowList().filter(function (o) {
        return o !== w && isGroupable(o) && className(o) === cls;
    });
    if (others.length === 0) return;
    addToGroup(others[0], w);
}

function onGeometry(w) {
    if (syncing) return;
    var g = groupOf(w);
    if (!g) return;
    if (workspace.activeWindow === w) {
        g.members.forEach(function (m) { if (m !== w) copyGeometry(w, m); });
        g.current = w;
        reserveRoom(g);
    }
    layoutBars();
}

function onVisibilityChange() { pushState(); layoutBars(); }

function track(w) {
    if (!w || tracked.indexOf(w) !== -1) return;
    tracked.push(w);
    if (isBar(w) || className(w) === "") {
        // la clase puede llegar tarde: reintentar cuando cambie
        if (w.windowClassChanged) w.windowClassChanged.connect(function () {
            prepareBar(w); maybeAutoGroup(w); pushState();
        });
    }
    w.frameGeometryChanged.connect(function () { onGeometry(w); });
    w.captionChanged.connect(function () {
        if (isBar(w)) prepareBar(w); else pushState();
    });
    ["minimizedChanged", "fullScreenChanged", "desktopsChanged"].forEach(function (s) {
        if (w[s]) w[s].connect(onVisibilityChange);
    });
}

function prepareBar(w) {
    if (!isBar(w)) return;
    try {
        w.skipTaskbar = true;
        w.skipSwitcher = true;
        w.skipPager = true;
        w.noBorder = true;
    } catch (e) { }
    layoutBars();
    syncLayers(workspace.activeWindow);
}

// ---------- estado hacia la interfaz ----------

function visibleNow(w) {
    if (!w || w.minimized || w.fullScreen) return false;
    if (w.onAllDesktops) return true;
    var d = w.desktops;
    if (!d || d.length === 0) return true;
    for (var i = 0; i < d.length; i++) if (d[i] === workspace.currentDesktop) return true;
    return false;
}

function winInfo(w) {
    return {
        id: wid(w),
        title: String(w.caption),
        icon: String(w.desktopFileName || w.resourceClass),
        cls: className(w)
    };
}

function buildState() {
    var gs = groups.map(function (g) {
        return {
            id: g.id,
            visible: visibleNow(g.current),
            current: g.current ? wid(g.current) : "",
            overlay: posOf(g) === "titlebar",
            tabs: g.members.map(winInfo)
        };
    });
    var ws = workspace.windowList().filter(isGroupable).map(function (w) {
        var info = winInfo(w);
        var g = groupOf(w);
        info.group = g ? g.id : null;
        return info;
    });
    return { v: 1, groups: gs, windows: ws };
}

function pushState(force) {
    var s = JSON.stringify(buildState());
    if (!force && s === lastState) return;
    lastState = s;
    callDBus(UI_SERVICE, UI_PATH, UI_IFACE, "update", s, function (reply) {
        applySettings(reply);
        layoutBars();
    });
}

// ---------- acciones ----------

function activate(w) {
    if (!w) return;
    if (w.minimized) w.minimized = false;
    workspace.activeWindow = w;
}

function cycle(dir) {
    var cur = workspace.activeWindow;
    if (!cur) return;
    var g = groupOf(cur);
    if (!g) { osd("Esta ventana no está en un grupo"); return; }
    var n = g.members.length;
    activate(g.members[(g.members.indexOf(cur) + dir + n) % n]);
}

function markOrJoin() {
    var w = workspace.activeWindow;
    if (!isGroupable(w)) return;
    if (pending === null) {
        pending = w;
        osd("Ventana marcada. Ve a otra ventana y presiona de nuevo para unirla.");
        return;
    }
    if (pending === w) { pending = null; osd("Marca cancelada"); return; }
    addToGroup(pending, w);
    pending = null;
    osd("Ventana unida al grupo");
    pushState();
}

function leaveGroup(w) {
    w = w || workspace.activeWindow;
    if (!w || !groupOf(w)) { osd("Esta ventana no está en un grupo"); return; }
    removeFromGroup(w);
    osd("Ventana sacada del grupo");
    pushState();
}

function groupSameApp() {
    var w = workspace.activeWindow;
    if (!isGroupable(w)) return;
    var cls = className(w);
    var same = workspace.windowList().filter(function (o) {
        return o !== w && isGroupable(o) && className(o) === cls;
    });
    if (same.length === 0) { osd("No hay otras ventanas de esta app"); return; }
    same.forEach(function (o) { addToGroup(w, o); });
    osd("Agrupadas " + (same.length + 1) + " ventanas de la misma app");
    pushState();
}

function toggleAuto() {
    autoOverride = !autoIsOn();
    osd(autoOverride ? "Agrupar automático: activado" : "Agrupar automático: desactivado");
}

// comandos que manda la interfaz
function runCommand(c) {
    var w = c.id ? findById(c.id) : null;
    switch (c.op) {
    case "activate": activate(w); break;
    case "close": if (w) w.closeWindow(); break;
    case "ungroup": if (w) removeFromGroup(w); break;
    case "join":
        var t = findById(c.target);
        if (w && t && isGroupable(w)) addToGroup(t, w);
        break;
    case "group":
        var ws = (c.ids || []).map(findById).filter(isGroupable);
        for (var i = 1; i < ws.length; i++) addToGroup(ws[0], ws[i]);
        if (ws.length > 0) activate(ws[0]);
        break;
    case "reorder":
        var g = w ? groupOf(w) : null;
        if (g) {
            g.members.splice(g.members.indexOf(w), 1);
            g.members.splice(Math.max(0, Math.min(c.index, g.members.length)), 0, w);
        }
        break;
    case "resync": break;
    }
}

function pullCommands() {
    callDBus(UI_SERVICE, UI_PATH, UI_IFACE, "popCommands", function (reply) {
        var cmds = [];
        try { cmds = JSON.parse(reply); cmds.forEach(runCommand); } catch (e) { }
        // tras un cambio de ajustes ("resync"), aplicar la lista automática
        // también a las ventanas que ya estaban abiertas
        if (cmds.some(function (c) { return c.op === "resync"; })) {
            workspace.windowList().forEach(maybeAutoGroup);
        }
        groups.forEach(reserveRoom);
        pushState(true);
        layoutBars();
    });
}

// ---------- atajos (se cambian en Preferencias > Atajos > KWin) ----------

function sc(title, keys, fn) { registerShortcut(title, title, keys, fn); }

sc("WindowTabs: Siguiente ventana del grupo", "Ctrl+Alt+Right", function () { cycle(1); });
sc("WindowTabs: Ventana anterior del grupo", "Ctrl+Alt+Left", function () { cycle(-1); });
sc("WindowTabs: Marcar / unir ventana", "Meta+G", markOrJoin);
sc("WindowTabs: Sacar ventana del grupo", "Meta+Shift+G", function () { leaveGroup(); });
sc("WindowTabs: Agrupar todas las de esta app", "Meta+Ctrl+G", groupSameApp);
sc("WindowTabs: Activar/desactivar agrupar automático", "Meta+Alt+G", toggleAuto);
sc("WindowTabs: Comando de la interfaz", "", pullCommands);

// ---------- eventos ----------

workspace.windowAdded.connect(function (w) {
    track(w);
    prepareBar(w);
    maybeAutoGroup(w);
    pushState();
});

workspace.windowRemoved.connect(function (w) {
    removeFromGroup(w);
    if (pending === w) pending = null;
    var i = tracked.indexOf(w);
    if (i !== -1) tracked.splice(i, 1);
    pushState();
    layoutBars();
});

workspace.windowActivated.connect(function (w) {
    if (!w) { syncLayers(null); return; }
    if (isBar(w)) {
        // clic en la barra: devolver el foco a la ventana del grupo
        var bg = groupById(barGroupId(w));
        if (bg && bg.current) workspace.activeWindow = bg.current;
        return;
    }
    var g = groupOf(w);
    if (g) {
        var prev = g.current;
        if (prev && prev !== w) {
            copyGeometry(prev, w);
            if (settings.hideInactive) prev.minimized = true;
        }
        g.current = w;
        reserveRoom(g);
        layoutBars();
    }
    syncLayers(w);
    pushState();
});

if (workspace.currentDesktopChanged) {
    workspace.currentDesktopChanged.connect(onVisibilityChange);
}

workspace.windowList().forEach(function (w) {
    track(w);
    prepareBar(w);
    maybeAutoGroup(w);
});
pushState(true);
