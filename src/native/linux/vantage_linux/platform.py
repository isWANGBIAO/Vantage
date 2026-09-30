"""Linux desktop integrations; GTK4, portal-aware pickers and StatusNotifier."""
from __future__ import annotations
import locale
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk


def system_locale():
    return locale.getlocale()[0] or os.environ.get("LANG", "C")


def desktop_quote(value):
    # Desktop Entry Exec quoting is not POSIX shell quoting; % must be escaped.
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$").replace("%", "%%") + '"'


def apply_autostart(enabled, command, config_home=None):
    directory = Path(config_home or os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autostart"
    target = directory / "org.vantage.Native.desktop"
    if not enabled:
        target.unlink(missing_ok=True)
        return
    directory.mkdir(parents=True, exist_ok=True)
    body = "[Desktop Entry]\nType=Application\nName=Vantage\nComment=Vantage native GTK4 client\nExec=" + " ".join(desktop_quote(x) for x in command) + "\nTerminal=false\nX-GNOME-Autostart-enabled=true\n"
    fd, temp = tempfile.mkstemp(prefix=".vantage-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.replace(temp, target)
    finally:
        Path(temp).unlink(missing_ok=True)


def choose_file(parent, title, callback, folder=False, save=False, filename=None):
    action = Gtk.FileChooserAction.SELECT_FOLDER if folder else Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN
    chooser = Gtk.FileChooserNative.new(title, parent, action, "选择" if not save else "保存", "取消")
    if save and filename:
        chooser.set_current_name(filename)
    def response(dialog, code):
        file = dialog.get_file()
        if code == Gtk.ResponseType.ACCEPT and file:
            path = file.get_path()
            if path:
                callback(path)
        dialog.destroy()
    chooser.connect("response", response)
    chooser.show()
    return chooser


def open_folder(path):
    target = Path(path).expanduser()
    if not target.is_dir():
        raise RuntimeError("目录不存在 / Directory does not exist")
    Gio.AppInfo.launch_default_for_uri(target.absolute().as_uri(), None)


class Recorder:
    """Explicit user-started local recording. No automatic microphone access."""
    def __init__(self):
        self.process = None
        self.path = None
        self.tool = shutil.which("pw-record") or shutil.which("arecord")

    def start(self):
        if not self.tool:
            raise RuntimeError("录音需要 PipeWire 的 pw-record 或 ALSA arecord；也可选择音频文件")
        if self.process:
            return
        fd, self.path = tempfile.mkstemp(prefix="vantage-voice-", suffix=".wav")
        os.close(fd)
        args = [self.tool, "--rate", "16000", "--channels", "1", self.path] if Path(self.tool).name == "pw-record" else [self.tool, "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", self.path]
        self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(self):
        if self.process:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            code = self.process.returncode
            self.process = None
            if code not in {0, 1, -signal.SIGINT}:
                self.discard()
                raise RuntimeError("麦克风不可用或权限被拒绝 / Microphone unavailable or permission denied")
        return self.path

    def discard(self):
        if self.process:
            self.stop()
        if self.path:
            Path(self.path).unlink(missing_ok=True)
            self.path = None


TRAY_XML = '''<node><interface name="org.kde.StatusNotifierItem">
<method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
<method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
<property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
<property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
<property name="IconName" type="s" access="read"/><property name="ItemIsMenu" type="b" access="read"/>
<property name="Menu" type="o" access="read"/><signal name="NewStatus"><arg type="s"/></signal>
</interface><interface name="com.canonical.dbusmenu">
<method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/><arg type="u" direction="out"/><arg type="(ia{sv}av)" direction="out"/></method>
<method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/><arg type="a(ia{sv})" direction="out"/></method>
<method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
<method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/><arg type="u" direction="in"/></method>
<method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
<property name="Version" type="u" access="read"/><property name="TextDirection" type="s" access="read"/>
<property name="Status" type="s" access="read"/><property name="IconThemePath" type="as" access="read"/>
</interface></node>'''


class Tray:
    """Uses the freedesktop StatusNotifier protocol; no GTK3 mixing.

    GNOME without an indicator extension has no tray host. In that case closing
    the window exits normally rather than hiding an unreachable application.
    """
    def __init__(self, show, quit_app, changed=lambda available: None):
        self.available = False
        self.show = show
        self.quit_app = quit_app
        self.changed = changed
        self.bus = None
        self.registrations = []
        try:
            self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            info = Gio.DBusNodeInfo.new_for_xml(TRAY_XML)
            self.registrations = [self.bus.register_object("/StatusNotifierItem", info.interfaces[0], self.call, self.get_property, None), self.bus.register_object("/Menu", info.interfaces[1], self.call, self.get_property, None)]
            self.watch = Gio.bus_watch_name_on_connection(self.bus, "org.kde.StatusNotifierWatcher", Gio.BusNameWatcherFlags.NONE, self.appeared, self.vanished)
        except GLib.Error:
            self.available = False

    def appeared(self, connection, name, owner):
        connection.call(name, "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem", GLib.Variant("(s)", ("/StatusNotifierItem",)), None, Gio.DBusCallFlags.NONE, 5000, None, self.registered)

    def registered(self, connection, result):
        try:
            connection.call_finish(result)
            self.available = True
        except GLib.Error:
            self.available = False
        self.changed(self.available)

    def vanished(self, *args):
        self.available = False
        self.changed(False)

    def get_property(self, connection, sender, path, interface, name):
        properties = {"Category": ("s", "ApplicationStatus"), "Id": ("s", "vantage"), "Title": ("s", "Vantage"), "Status": ("s", "Active" if path != "/Menu" else "normal"), "IconName": ("s", "applications-science-symbolic"), "ItemIsMenu": ("b", False), "Menu": ("o", "/Menu"), "Version": ("u", 3), "TextDirection": ("s", "ltr"), "IconThemePath": ("as", [])}
        return GLib.Variant(*properties[name]) if name in properties else None

    def menu_props(self, item):
        return {"label": GLib.Variant("s", "显示 Vantage / Show" if item == 1 else "退出 / Quit"), "enabled": GLib.Variant("b", True), "visible": GLib.Variant("b", True)}

    def call(self, connection, sender, path, interface, method, params, invocation):
        args = params.unpack()
        if method in {"Activate", "SecondaryActivate", "ContextMenu"}:
            self.show()
        elif method == "GetLayout":
            children = [GLib.Variant("(ia{sv}av)", (item, self.menu_props(item), [])) for item in (1, 2)]
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, (0, {"children-display": GLib.Variant("s", "submenu")}, children))))
            return
        elif method == "GetGroupProperties":
            invocation.return_value(GLib.Variant("(a(ia{sv}))", ([(item, self.menu_props(item)) for item in args[0] if item in {1, 2}],)))
            return
        elif method == "GetProperty":
            invocation.return_value(GLib.Variant("(v)", (self.menu_props(args[0]).get(args[1], GLib.Variant("s", "")),)))
            return
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
            return
        elif method == "Event" and args[1] == "clicked":
            (self.show if args[0] == 1 else self.quit_app)()
        invocation.return_value(None)
