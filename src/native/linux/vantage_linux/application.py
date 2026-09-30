"""Genuine GTK4 application: all pages use native widgets and Cairo charts."""
from __future__ import annotations
import json
import os
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango
from .client import ClientError, JobObserver, complete_result, payload_text, provider_patch
from .charts import Chart
from .markdown import markdown_blocks
from .chat_draft import ChatDraftAttempt
from .platform import Recorder, Tray, apply_autostart, choose_file, open_folder, system_locale

CSS = b'''
window { background: #10151b; color: #e4e9ef; }
.sidebar { background: #151c24; padding: 12px; }
.sidebar row { padding: 10px; border-radius: 8px; }
.sidebar row:selected { background: #263c40; color: #75d8c2; }
.page { padding: 24px; }
.card { background: #19222c; border: 1px solid #2c3846; border-radius: 12px; padding: 16px; }
.title-1 { font-size: 27px; font-weight: 700; }
.title-2 { font-size: 21px; font-weight: 700; }
.title-3 { font-size: 16px; font-weight: 600; }
.metric { font-size: 29px; font-weight: 700; color: #75d8c2; }
.dim-label { color: #9daab9; }
.error { color: #ffaaa5; }
button { padding: 8px 12px; }
button.suggested-action { background: #23796b; color: white; }
textview, textview text { background: transparent; color: inherit; }
entry { min-height: 30px; }
'''
PAGES = [("dashboard", "总览", "Overview"), ("plan", "行动计划", "Action plan"), ("chat", "聊天", "Chat"), ("projects", "项目", "Projects"), ("expenses", "财务", "Finances"), ("plots", "图表", "Charts"), ("face", "人脸与相机", "Face & camera"), ("usage", "模型用量", "Usage"), ("logs", "系统日志", "Logs"), ("settings", "设置", "Settings")]


def box(spacing=12, horizontal=False):
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL if horizontal else Gtk.Orientation.VERTICAL, spacing=spacing)


def label(text, css=None, wrap=True):
    widget = Gtk.Label(label=str(text), xalign=0, wrap=wrap, selectable=True)
    if css:
        widget.add_css_class(css)
    return widget


def button(text, callback, primary=False):
    widget = Gtk.Button(label=text)
    widget.connect("clicked", lambda _: callback())
    if primary:
        widget.add_css_class("suggested-action")
    return widget


def clear(widget):
    while child := widget.get_first_child():
        widget.remove(child)


class MarkdownView(Gtk.TextView):
    def __init__(self):
        super().__init__(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        buf = self.get_buffer()
        styles = {
            "h1": {"weight": Pango.Weight.BOLD, "scale": 1.65, "pixels_above_lines": 12, "pixels_below_lines": 7},
            "h2": {"weight": Pango.Weight.BOLD, "scale": 1.35, "pixels_above_lines": 10, "pixels_below_lines": 5},
            "h3": {"weight": Pango.Weight.BOLD, "scale": 1.15, "pixels_above_lines": 8},
            "bold": {"weight": Pango.Weight.BOLD}, "italic": {"style": Pango.Style.ITALIC},
            "strike": {"strikethrough": True}, "code": {"family": "monospace", "background": "#28333f"},
            "pre": {"family": "monospace", "background": "#19222c", "left_margin": 16, "pixels_above_lines": 2},
            "table": {"family": "monospace", "pixels_above_lines": 3},
            "table-head": {"family": "monospace", "weight": Pango.Weight.BOLD, "pixels_above_lines": 5},
            "quote": {"style": Pango.Style.ITALIC, "left_margin": 18, "foreground": "#9daab9"},
            "list": {"left_margin": 8, "pixels_above_lines": 3},
            "rule": {"foreground": "#617080"}, "link": {"foreground": "#63a9ef", "underline": Pango.Underline.SINGLE},
        }
        for name, properties in styles.items():
            buf.create_tag(name, **properties)

    def set_markdown(self, source):
        self.source = str(source)
        buf = self.get_buffer()
        buf.set_text("")
        for style, runs in markdown_blocks(source):
            start = buf.get_char_count()
            for text, inline in runs:
                inline_start = buf.get_char_count()
                buf.insert(buf.get_end_iter(), text)
                if inline:
                    buf.apply_tag_by_name(inline, buf.get_iter_at_offset(inline_start), buf.get_end_iter())
            buf.insert(buf.get_end_iter(), "\n")
            if style != "body":
                buf.apply_tag_by_name(style, buf.get_iter_at_offset(start), buf.get_end_iter())


def set_view_text(view, text):
    if isinstance(view, MarkdownView):
        view.set_markdown(text)
    else:
        view.get_buffer().set_text(str(text))


def text_view(text="", editable=False, height=150, markdown=False):
    widget = MarkdownView() if markdown else Gtk.TextView(editable=editable, cursor_visible=editable, wrap_mode=Gtk.WrapMode.WORD_CHAR)
    widget.set_left_margin(10)
    widget.set_right_margin(10)
    widget.set_top_margin(10)
    widget.set_bottom_margin(10)
    set_view_text(widget, text)
    scroller = Gtk.ScrolledWindow(min_content_height=height, vexpand=True)
    scroller.set_child(widget)
    return scroller, widget


def buffer_text(view):
    buf = view.get_buffer()
    return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)


def scalar(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "✓" if value else "—"
    return str(value)


def data_view(data, depth=0):
    """Native expandable semantic rows for additive backend metadata."""
    panel = box(7)
    if isinstance(data, dict):
        for key, value in data.items():
            if "api_key" in key.lower() or key.lower() in {"prompt_payload", "input", "system_prompt"}:
                continue
            if isinstance(value, (dict, list)):
                expander = Gtk.Expander(label=str(key).replace("_", " "))
                expander.set_child(data_view(value, depth + 1))
                expander.set_expanded(depth == 0 and len(data) < 6)
                panel.append(expander)
            else:
                row = box(horizontal=True)
                key_label = label(str(key).replace("_", " "), "dim-label")
                key_label.set_size_request(160, -1)
                row.append(key_label)
                value_label = label(scalar(value))
                value_label.set_hexpand(True)
                row.append(value_label)
                panel.append(row)
    elif isinstance(data, list):
        for value in data:
            if isinstance(value, (dict, list)):
                child = data_view(value, depth + 1)
                child.add_css_class("card")
                panel.append(child)
            else:
                panel.append(label(scalar(value)))
        if not data:
            panel.append(label("暂无数据 / No data", "dim-label"))
    else:
        panel.append(label(scalar(data)))
    return panel


class Window(Gtk.ApplicationWindow):
    def __init__(self, application, host, launch_command, smoke=False):
        super().__init__(application=application, title="Vantage", default_width=1280, default_height=860)
        self.host, self.client = host, host.client
        self.launch_command = launch_command
        self.smoke = smoke
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="vantage-ui")
        self.pending = set()
        self.state = {}
        self.language = "zh-CN"
        self.connected = False
        self.closed = False
        self.page = "dashboard"
        self.generation = 0
        self.job_observer = None
        self.job_id = None
        self.job_render = {"analysis": "", "plan": ""}
        self.chat_stop = None
        self.chat_context_version = None
        self.chat_clear_epoch = 0
        self.failed_chat_attempt = None
        self.camera_stop = None
        self.recorder = Recorder()
        self.models = []
        self.pages = {}
        self.nav_rows = {}
        self.tray = None
        self.snapshot = {}
        self.face_last_status = None
        self.last_plan_identity = None
        self._build_shell()
        self.connect("close-request", self.close_requested)
        if not smoke:
            self.tray = Tray(self.present, self.quit_app)
        self.connect_backend()
        GLib.timeout_add_seconds(5, self.poll)

    def tr(self, zh, en):
        return en if self.language == "en-US" else zh

    def _build_shell(self):
        header = Gtk.HeaderBar()
        header.set_title_widget(label("Vantage", "title-3"))
        header.pack_end(button("↻", self.refresh))
        menu = Gio.Menu()
        menu.append("退出 / Quit", "app.quit")
        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu)
        header.pack_end(menu_button)
        self.set_titlebar(header)
        root = box(0)
        self.notice = label("正在连接本地后端… / Connecting…")
        self.notice.set_margin_start(20)
        self.notice.set_margin_top(8)
        self.notice.set_margin_bottom(8)
        root.append(self.notice)
        body = box(0, horizontal=True)
        body.set_vexpand(True)
        sidebar = box()
        sidebar.add_css_class("sidebar")
        sidebar.set_size_request(205, -1)
        sidebar.append(label("VANTAGE", "title-2"))
        sidebar.append(label("原生 Linux · GTK4", "dim-label"))
        self.nav = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.nav.add_css_class("navigation-sidebar")
        for key, zh, en in PAGES:
            row = Gtk.ListBoxRow()
            row.key = key
            row.set_child(label(zh))
            self.nav.append(row)
            self.nav_rows[key] = row
        self.nav.connect("row-selected", lambda _, row: self.navigate(row.key) if row else None)
        sidebar.append(self.nav)
        body.append(sidebar)
        self.stack = Gtk.Stack(hexpand=True, vexpand=True, transition_type=Gtk.StackTransitionType.CROSSFADE)
        for key, zh, en in PAGES + [("onboarding", "开始使用", "Welcome")]:
            content = box()
            content.add_css_class("page")
            scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
            scroll.set_child(content)
            self.pages[key] = content
            self.stack.add_named(scroll, key)
        body.append(self.stack)
        root.append(body)
        self.set_child(root)
        self.nav.select_row(self.nav_rows["dashboard"])

    def run_async(self, key, work, done=None, on_error=None):
        if key in self.pending or self.closed:
            return False
        self.pending.add(key)
        def worker():
            try:
                value = work()
                error = None
            except Exception as exc:
                value, error = None, exc
            def finish():
                self.pending.discard(key)
                if self.closed:
                    return GLib.SOURCE_REMOVE
                if error is not None:
                    if on_error:
                        on_error(error)
                    else:
                        self.show_error(error)
                elif done:
                    done(value)
                return GLib.SOURCE_REMOVE
            GLib.idle_add(finish)
        self.pool.submit(worker)
        return True

    def show_error(self, error):
        # Transport errors are intentionally sanitized. Do not log request data.
        self.notice.set_text(str(error) if isinstance(error, (ClientError, RuntimeError)) else self.tr("操作失败，请查看后端日志", "Operation failed; inspect backend logs"))
        self.notice.add_css_class("error")

    def notice_ok(self, text):
        self.notice.remove_css_class("error")
        self.notice.set_text(text)

    def connect_backend(self):
        def load():
            caps = self.host.connect()
            return {"caps": caps, "state": self.client.request("/api/v1/settings"), "onboarding": self.client.request("/api/v1/onboarding"), "models": self.client.request("/api/v1/models")}
        def loaded(data):
            self.connected = True
            self.apply_state(data["state"])
            self.models = data["models"].get("model_options", [])
            self.notice_ok(self.tr("本地后端已连接 · 原生 GTK4", "Local backend connected · Native GTK4"))
            if not data["onboarding"].get("completed"):
                self.build_onboarding()
                self.stack.set_visible_child_name("onboarding")
                self.nav.set_sensitive(False)
            else:
                self.refresh()
                self.discover_job()
        self.run_async("connect", load, loaded)

    def apply_state(self, state):
        self.state = state
        self.models = [{"model": model, "provider_route": route, "label": f"{provider.get('name') or route} / {model}"} for route, provider in state.get("provider", {}).get("providers", {}).items() if provider.get("enabled", True) for model in list(dict.fromkeys(provider.get("models", []) + ([provider["model"]] if provider.get("model") else [])))]
        self.language = state.get("settings", {}).get("display_language", "system")
        if self.language == "system":
            self.language = "zh-CN" if system_locale().lower().startswith("zh") else "en-US"
        for key, zh, en in PAGES:
            self.nav_rows[key].get_child().set_text(self.tr(zh, en))
        theme = state.get("settings", {}).get("theme_mode", "auto")
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", theme == "dark")
        # CSS is only applied in dark mode; light/auto uses native platform colors.
        if hasattr(self, "css"):
            Gtk.StyleContext.remove_provider_for_display(self.get_display(), self.css)
        if theme == "dark":
            self.css = Gtk.CssProvider()
            self.css.load_from_data(CSS)
            Gtk.StyleContext.add_provider_for_display(self.get_display(), self.css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def navigate(self, page):
        if self.page == "face" and page != "face":
            self.stop_camera()
        if self.page == "chat" and page != "chat":
            self.stop_chat()
            self.recorder.discard()
        self.page = page
        self.generation += 1
        self.stack.set_visible_child_name(page)
        if self.connected:
            self.refresh()

    def heading(self, page, subtitle=""):
        content = self.pages[page]
        clear(content)
        _, zh, en = next(item for item in PAGES if item[0] == page)
        row = box(horizontal=True)
        title = label(self.tr(zh, en), "title-1")
        title.set_hexpand(True)
        row.append(title)
        row.append(button(self.tr("刷新", "Refresh"), self.refresh))
        content.append(row)
        if subtitle:
            content.append(label(subtitle, "dim-label"))
        return content

    def refresh(self):
        if not self.connected:
            self.connect_backend()
            return
        methods = {"dashboard": self.load_dashboard, "plan": self.load_plan, "chat": self.load_chat, "projects": self.load_projects, "expenses": self.load_expenses, "plots": self.load_plots, "face": self.load_face, "usage": self.load_usage, "logs": self.load_logs, "settings": self.load_settings}
        methods[self.page]()

    def load_data(self, page, paths, render):
        generation = self.generation
        def work():
            return {key: self.client.request(path) for key, path in paths.items()}
        def done(data):
            self.snapshot[page] = data
            if self.page == page and generation == self.generation:
                render(data)
        self.run_async(f"read-{page}", work, done)

    def load_dashboard(self):
        def render(data):
            content = self.heading("dashboard", self.tr("今天的状态、资源与专注时间", "Your activity, resources and focus today"))
            stats = data["stats"]
            self.dashboard_metrics = {}
            cards = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, min_children_per_line=2, row_spacing=12, column_spacing=12)
            for name, value in [("CPU", f"{stats.get('cpu_usage', '—')}%"), (self.tr("内存", "Memory"), f"{stats.get('memory_used_gb', '—')} GB"), (self.tr("可用磁盘", "Free disk"), f"{stats.get('disk_free_gb', '—')} GB"), (self.tr("相机", "Camera"), self.tr("在线", "Online") if data["status"].get("camera_online") else self.tr("离线", "Offline"))]:
                card = box()
                card.add_css_class("card")
                card.set_size_request(175, 95)
                card.append(label(name, "dim-label"))
                metric = label(value, "metric")
                self.dashboard_metrics[name] = metric
                card.append(metric)
                cards.append(card)
            content.append(cards)
            content.append(label(self.tr("专注与久坐", "Focus & sedentary status"), "title-3"))
            focus = data["sedentary"]
            focus_card = box(horizontal=True)
            focus_card.add_css_class("card")
            focus_card.append(label(f"{focus.get('duration_minutes', 0)} " + self.tr("分钟", "min"), "metric"))
            focus_card.append(label(self.tr("当前专注" if focus.get("active_timer") == "focus" else "休息 / 未检测到活动", "Focused" if focus.get("active_timer") == "focus" else "Away / no current activity")))
            content.append(focus_card)
            content.append(label(self.tr("空气质量", "Air quality"), "title-3"))
            air = data["air"]
            content.append(label(f"AQI {air.get('aqi')} · {air.get('level', '')}" if air.get("aqi") is not None else self.tr("当前位置的空气质量暂不可用", "Air quality is unavailable for the current location"), "dim-label"))
            diagnostics = Gtk.Expander(label=self.tr("状态详情", "Status details"))
            diagnostics.set_child(data_view({"focus": focus, "air": air}))
            content.append(diagnostics)
            content.append(label(self.tr("行动计划", "Action plan"), "title-3"))
            today = data["today"]
            plan_scroll, self.dashboard_plan = text_view((today.get("plan") or {}).get("body", self.tr("暂无今日计划", "No saved plan today")), height=180, markdown=True)
            plan_scroll.set_vexpand(False)
            content.append(plan_scroll)
            actions = box(horizontal=True)
            actions.append(button(self.tr("查看行动计划", "Open action plan"), lambda: self.nav.select_row(self.nav_rows["plan"]), True))
            actions.append(button(self.tr("照片目录", "Photos folder"), lambda: self.open_media("photo")))
            actions.append(button(self.tr("截图目录", "Screenshots folder"), lambda: self.open_media("screenshot")))
            content.append(actions)
            latest = data["media"]
            exp = Gtk.Expander(label=self.tr("最近媒体（点击显示）", "Latest media (reveal)"))
            media_box = box()
            exp.set_child(media_box)
            def reveal(_, param):
                if exp.get_expanded() and not media_box.get_first_child():
                    media_box.append(data_view(latest))
                    for value in latest.values():
                        path = value.get("url") if isinstance(value, dict) else value
                        if isinstance(path, str) and path.startswith(("/api/v1/media/", "/static/photos/", "/static/screenshots/")):
                            self.load_picture(path, media_box)
            exp.connect("notify::expanded", reveal)
            content.append(exp)
        self.load_data("dashboard", {"status": "/api/v1/system/status", "stats": "/api/v1/system/statistics", "sedentary": "/api/v1/health/sedentary", "air": "/api/v1/system/air-quality", "today": "/api/v1/action-plan/today", "media": "/api/v1/media/latest"}, render)

    def open_media(self, kind):
        self.run_async("open-folder", lambda: self.client.request("/api/v1/media/open-folder", "POST", {"type": kind}, {"X-Vantage-Intent": "open-folder"}), lambda _: self.notice_ok(self.tr("已请求打开目录", "Folder requested")))

    def model_controls(self, parent):
        row = box(horizontal=True)
        options = [self.tr("后端默认模型", "Backend default")] + [str(m.get("label") or m.get("model")) for m in self.models]
        model = Gtk.DropDown.new_from_strings(options)
        model.set_hexpand(True)
        row.append(model)
        reasoning = Gtk.DropDown.new_from_strings(["default", "low", "medium", "high", "xhigh", "max"])
        row.append(reasoning)
        tier = Gtk.DropDown.new_from_strings(["default", "priority", "fast"])
        row.append(tier)
        parent.append(row)
        def read():
            result = {}
            index = model.get_selected()
            if 0 < index <= len(self.models):
                result.update({key: self.models[index - 1][key] for key in ("model", "provider_route") if self.models[index - 1].get(key)})
            if reasoning.get_selected() > 0:
                result["reasoning_effort"] = reasoning.get_selected_item().get_string()
            if tier.get_selected() > 0:
                result["service_tier"] = tier.get_selected_item().get_string()
            return result
        return read

    def load_plan(self):
        def render(data):
            content = self.heading("plan", self.tr("任务由后端持有；切换页面或断线不会取消生成", "The backend owns jobs; navigating away or disconnecting does not cancel"))
            self.plan_options = self.model_controls(content)
            row = box(horizontal=True)
            self.replace = Gtk.CheckButton(label=self.tr("成功后替换今日计划", "Replace today's plan after success"))
            row.append(self.replace)
            self.generate_button = button(self.tr("生成计划", "Generate"), self.create_job, True)
            row.append(self.generate_button)
            row.append(button(self.tr("停止任务", "Cancel job"), self.cancel_job))
            content.append(row)
            self.job_label = label(self.tr("没有运行中的任务", "No active job"), "dim-label")
            content.append(self.job_label)
            for section, title in [("analysis", self.tr("分析", "Analysis")), ("plan", self.tr("计划", "Plan"))]:
                content.append(label(title, "title-3"))
                scroll, view = text_view((data["today"].get(section) or {}).get("body", ""), height=190, markdown=True)
                setattr(self, f"plan_{section}_view", view)
                content.append(scroll)
            details = Gtk.Expander(label=self.tr("生成信息与后台调度", "Generation details & scheduler"))
            details.set_child(data_view({"metadata": data["today"].get("meta", {}), "scheduler": data["scheduler"], "jobs": data["jobs"].get("jobs", [])}))
            content.append(details)
            active = data["jobs"].get("active")
            if active:
                self.observe_job(active["id"])
                self.job_label.set_text(f"{active['status']} · {active['id']} · {json.dumps(active.get('request', {}), ensure_ascii=False)}")
        self.load_data("plan", {"today": "/api/v1/action-plan/today", "jobs": "/api/v1/action-plan/jobs", "scheduler": "/api/v1/action-plan/scheduler"}, render)

    def discover_job(self):
        self.run_async("discover-jobs", lambda: self.client.request("/api/v1/action-plan/jobs"), lambda data: self.observe_job(data["active"]["id"]) if data.get("active") else None)

    def create_job(self):
        options = self.plan_options()
        options["replace_today"] = self.replace.get_active()
        self.run_async("create-job", lambda: self.client.request("/api/v1/action-plan/jobs", "POST", options), lambda value: self.observe_job(value["id"]))

    def observe_job(self, job_id):
        if self.job_observer and self.job_id == job_id and not self.job_observer.stop.is_set():
            return
        if self.job_observer:
            self.job_observer.stop.set()
        self.job_id = job_id
        self.job_render = {"analysis": "", "plan": ""}
        observer = JobObserver(self.client, job_id)
        self.job_observer = observer
        def emit(kind, data):
            def update():
                if self.closed or observer is not self.job_observer:
                    return False
                self.job_update(kind, data)
                return False
            GLib.idle_add(update)
        def observe():
            try:
                observer.run(emit)
            except Exception as exc:
                emit("reconnecting", {"message": str(exc)})
            finally:
                observer.stop.set()
        threading.Thread(target=observe, daemon=True).start()

    def job_update(self, kind, data):
        if kind == "snapshot":
            if self.page == "plan" and hasattr(self, "job_label"):
                self.job_label.set_text(f"{data['status']} · {data['id']} · {json.dumps(data.get('request', {}), ensure_ascii=False)}")
            if data.get("status") in {"failed", "cancelled"}:
                self.notice_ok(self.tr("任务已失败或取消；保留上次完整计划", "Job failed or was cancelled; the last complete plan is preserved"))
        elif kind == "event":
            value = data.get("log", "")
            for section in ("analysis", "plan"):
                prefix = f"STREAM_{section.upper()}_CONTENT:"
                if value.startswith(prefix):
                    self.job_render[section] += payload_text(value[len(prefix):])
                    if self.page == "plan" and hasattr(self, f"plan_{section}_view"):
                        set_view_text(getattr(self, f"plan_{section}_view"), self.job_render[section])
        elif kind == "truncated":
            self.job_render = {"analysis": "", "plan": ""}
            if self.page == "plan":
                self.load_plan()
            self.notice_ok(self.tr("流记录已截断，正在重新读取完整结果", "Event history truncated; reloading authoritative state"))
        elif kind == "result":
            self.notice_ok(self.tr("新计划已完整保存", "New plan saved completely"))
            if self.page == "plan":
                self.load_plan()
        elif kind == "restarted":
            self.notice_ok(self.tr("后端已重启；正在恢复已保存计划和任务列表", "Backend restarted; restoring saved plan and current jobs"))
            if self.page == "plan":
                self.load_plan()
            if data["jobs"].get("active"):
                self.observe_job(data["jobs"]["active"]["id"])
        elif kind == "invalid_result":
            self.show_error(ClientError(data["message"]))
        elif kind == "reconnecting":
            self.notice_ok(self.tr("观察连接中断，正在自动重连；任务未取消", "Observer disconnected; reconnecting without cancelling the job"))

    def cancel_job(self):
        if self.job_id:
            job_id = self.job_id
            self.run_async("cancel-job", lambda: self.client.request(f"/api/v1/action-plan/jobs/{quote(job_id, safe='')}/cancel", "POST", {}), lambda _: self.load_plan() if self.page == "plan" else None)

    def load_chat(self):
        if self.chat_stop and not self.chat_stop.is_set():
            self.stack.set_visible_child_name("chat")
            return
        def render(data):
            draft = buffer_text(self.chat_input) if hasattr(self, "chat_input") else ""
            if self.failed_chat_attempt:
                failed, owner = self.failed_chat_attempt
                restored = failed.recover(data["context"], draft, clear_epoch=self.chat_clear_epoch, same_attempt=self.chat_stop is owner)
                if restored is not None:
                    draft = restored
                    self.failed_chat_attempt = None
                elif data["context"].get("context_version") != failed.context_version:
                    self.failed_chat_attempt = None
            content = self.heading("chat", self.tr("聊天上下文从后端读取；语音转录后可编辑再发送", "Conversation comes from the backend; review voice transcription before sending"))
            self.chat_options = self.model_controls(content)
            self.chat_context_version = data["context"].get("context_version")
            self.chat_messages = data["context"].get("messages", [])
            self.chat_text = "\n\n".join(f"{'你 / You' if m['role'] == 'user' else 'Vantage'}\n{m['content']}" for m in self.chat_messages)
            scroll, self.chat_view = text_view(self.chat_text, height=320, markdown=True)
            content.append(scroll)
            thought = Gtk.Expander(label=self.tr("思考与统计", "Reasoning & statistics"))
            thought_box = box()
            thought_box.append(data_view(data["context"].get("stats", {})))
            self.chat_thinking = label("")
            thought_box.append(self.chat_thinking)
            thought.set_child(thought_box)
            content.append(thought)
            content.append(label(self.tr("输入消息 · Ctrl+Enter 发送", "Message · Ctrl+Enter to send"), "dim-label"))
            scroll, self.chat_input = text_view(draft, editable=True, height=90)
            composer_frame = Gtk.Frame()
            composer_frame.set_child(scroll)
            content.append(composer_frame)
            keyboard = Gtk.EventControllerKey()
            def composer_key(controller, keyval, keycode, modifiers):
                if keyval in {Gdk.KEY_Return, Gdk.KEY_KP_Enter} and modifiers & Gdk.ModifierType.CONTROL_MASK:
                    self.send_chat()
                    return True
                return False
            keyboard.connect("key-pressed", composer_key)
            self.chat_input.add_controller(keyboard)
            actions = box(horizontal=True)
            actions.append(button(self.tr("发送", "Send"), self.send_chat, True))
            actions.append(button(self.tr("停止", "Stop"), self.stop_chat))
            actions.append(button(self.tr("清空聊天", "Clear chat"), lambda: self.confirm(self.tr("清空可见聊天记录？保留行动计划上下文。", "Clear the visible conversation? Action-plan context is retained."), self.clear_chat)))
            actions.append(button(self.tr("选择音频", "Audio file"), lambda: choose_file(self, self.tr("选择待转录的音频", "Select audio to transcribe"), self.transcribe)))
            self.record_button = button(self.tr("开始录音", "Record"), self.toggle_recording)
            self.record_button.set_sensitive(bool(self.recorder.tool))
            self.record_button.set_tooltip_text(self.tr("需要 pw-record 或 arecord；仅点击后访问麦克风", "Needs pw-record or arecord; microphone is only accessed after a click"))
            actions.append(self.record_button)
            content.append(actions)
        self.load_data("chat", {"context": "/api/v1/chat/context"}, render)

    def send_chat(self):
        if "chat-stream" in self.pending:
            self.notice_ok(self.tr("上一条请求正在结束，请稍候", "The previous request is finishing; please wait"))
            return
        original_draft = buffer_text(self.chat_input)
        message = original_draft.strip()
        if not message:
            return
        stop = threading.Event()
        self.chat_stop = stop
        self.failed_chat_attempt = None
        attempt = ChatDraftAttempt(original_draft, self.chat_context_version, self.chat_clear_epoch)
        request = {"message": message, **self.chat_options()}
        self.chat_input.get_buffer().set_text("")
        base = self.chat_text + f"\n\n你 / You\n{message}\n\nVantage\n"
        partial = {"content": "", "thinking": "", "done": False}
        def worker():
            for event in self.client.stream("/api/v1/chat", "POST", request, stop=stop):
                if event.get("error"):
                    raise ClientError(str(event["error"]))
                log = event.get("log", "")
                for key, prefix in (("content", "STREAM_CONTENT:"), ("thinking", "STREAM_THINKING:")):
                    if log.startswith(prefix):
                        partial[key] += payload_text(log[len(prefix):])
                if log.startswith("STREAM_ERROR:"):
                    raise ClientError("Chat generation failed")
                if event.get("done") is True:
                    partial["done"] = True
                text, thinking = base + partial["content"], partial["thinking"]
                def update(text=text, thinking=thinking):
                    if not self.closed and self.chat_stop is stop:
                        set_view_text(self.chat_view, text)
                        self.chat_thinking.set_text(thinking)
                    return False
                GLib.idle_add(update)
            if not stop.is_set() and not partial["done"]:
                raise ClientError("Chat stream ended before completion; reload context to verify saved messages")
            return self.client.request("/api/v1/chat/context")
        def restore_if_uncommitted(context):
            restored = attempt.recover(
                context, buffer_text(self.chat_input),
                clear_epoch=self.chat_clear_epoch, same_attempt=self.chat_stop is stop,
            )
            if restored is not None:
                self.chat_input.get_buffer().set_text(restored)
                self.failed_chat_attempt = None
            elif self.chat_stop is stop and context.get("context_version") != attempt.context_version:
                self.failed_chat_attempt = None
            return restored is not None
        def done(context):
            cancelled = stop.is_set()
            stop.set()
            if cancelled and not partial["done"]:
                restore_if_uncommitted(context)
            if self.chat_stop is stop and self.chat_clear_epoch == attempt.clear_epoch:
                self.chat_context_version = context.get("context_version")
                self.chat_text = "\n\n".join(f"{m['role']}\n{m['content']}" for m in context.get("messages", []))
                if self.page == "chat":
                    self.load_chat()
        def error(exc):
            cancelled = stop.is_set()
            stop.set()
            if self.chat_stop is stop and self.chat_clear_epoch == attempt.clear_epoch:
                self.failed_chat_attempt = (attempt, stop)
            if not cancelled:
                self.show_error(exc)
            def recovered(context):
                restore_if_uncommitted(context)
                if self.chat_stop is stop and self.chat_clear_epoch == attempt.clear_epoch:
                    self.chat_context_version = context.get("context_version")
                    if self.page == "chat":
                        self.load_chat()
            # A failed POST might have committed before the connection failed.
            # GET is the only recovery action; there is never an automatic resend.
            self.run_async(
                f"chat-recovery-{id(stop)}",
                lambda: self.client.request("/api/v1/chat/context"), recovered,
                lambda _: None,  # No authoritative version means no automatic restore.
            )
        self.run_async("chat-stream", worker, done, error)

    def stop_chat(self):
        if self.chat_stop:
            self.chat_stop.set()
            self.notice_ok(self.tr("已停止接收；正在重新读取会话状态", "Stopped receiving; reload context to verify the conversation"))
        self.client.cancel_stream("/api/v1/chat")

    def clear_chat(self):
        self.chat_clear_epoch += 1
        self.failed_chat_attempt = None
        self.stop_chat()
        def done(context):
            self.chat_context_version = context.get("context_version")
            self.chat_messages = context.get("messages", [])
            set_view_text(self.chat_view, "\n\n".join(m["content"] for m in self.chat_messages))
            self.chat_text = buffer_text(self.chat_view)
            self.notice_ok(self.tr("聊天上下文已清空", "Conversation context cleared"))
        self.run_async("clear-chat", lambda: self.client.request("/api/v1/chat/context", "DELETE"), done)

    def transcribe(self, path, recorded=False):
        generation = self.generation
        target_input = self.chat_input
        def work():
            try:
                return self.client.transcribe(path)
            finally:
                if recorded:
                    Path(path).unlink(missing_ok=True)
                    if self.recorder.path == path:
                        self.recorder.path = None
        self.run_async("transcribe", work, lambda data: target_input.get_buffer().set_text(data.get("transcription") or "") if self.page == "chat" and self.generation == generation else None)

    def toggle_recording(self):
        if "transcribe" in self.pending:
            self.notice_ok(self.tr("正在转录，请稍候再录音", "Transcription is in progress; wait before recording again"))
            return
        try:
            if self.recorder.process:
                path = self.recorder.stop()
                self.record_button.set_label(self.tr("开始录音", "Record"))
                self.transcribe(path, recorded=True)
            else:
                self.recorder.start()
                self.record_button.set_label(self.tr("停止并转录", "Stop & transcribe"))
                self.notice_ok(self.tr("正在录音；点击停止后将发送给已配置的语音服务", "Recording; stopping sends audio to your configured transcription provider"))
        except RuntimeError as exc:
            self.show_error(exc)

    def load_projects(self):
        def render(data):
            content = self.heading("projects")
            value = data["projects"]
            stats = value.get("stats", {})
            progress = Gtk.ProgressBar(show_text=True)
            progress.set_fraction(max(0, min(1, stats.get("completion_rate", 0))))
            progress.set_text(f"{stats.get('completed_tasks', 0)} / {stats.get('total_tasks', 0)}")
            content.append(progress)
            for key, title in [("pending", self.tr("待完成", "Pending")), ("completed", self.tr("已完成", "Completed"))]:
                content.append(label(title, "title-3"))
                for task in value.get("tasks", {}).get(key, []):
                    row = label(f"{'✓' if key == 'completed' else '○'}  {task.get('project', '')}  ·  {task.get('task', '')}")
                    row.add_css_class("card")
                    content.append(row)
            exp = Gtk.Expander(label=self.tr("近期提交", "Recent commits"))
            exp.set_child(data_view(value.get("commits", [])))
            content.append(exp)
        self.load_data("projects", {"projects": "/api/v1/projects/progress"}, render)

    def load_expenses(self):
        def render(data):
            content = self.heading("expenses", self.tr("数据来源：后端配置的工作簿", "Source: the workbook configured in the backend"))
            value = data["balance"]
            summary = value.get("summary", {})
            cards = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, column_spacing=12, row_spacing=12)
            metrics = [(self.tr("总资产", "Total assets"), (summary.get("assets", {}).get("total_assets") or {}).get("value")), (self.tr("负债", "Liabilities"), (summary.get("assets", {}).get("liabilities") or {}).get("value")), (self.tr("权益", "Equity"), (summary.get("assets", {}).get("equity") or {}).get("value")), (self.tr("日均支出", "Daily spend"), summary.get("time_cost", {}).get("daily_average")), (self.tr("每月必要预算", "Required budget/month"), (summary.get("budget") or {}).get("monthly_required")), (self.tr("每月可选预算", "Optional budget/month"), (summary.get("budget") or {}).get("monthly_optional"))]
            for title, number in metrics:
                card = box()
                card.add_css_class("card")
                card.append(label(title, "dim-label"))
                card.append(label(f"{number:,.2f}" if isinstance(number, (int, float)) else "—", "metric"))
                cards.append(card)
            content.append(cards)
            details = Gtk.Expander(label=self.tr("指标来源与时间成本", "Metric sources & time cost"))
            details.set_child(data_view(summary))
            content.append(details)
            content.append(data_view(value.get("suggestions", [])))
            for field, title, metrics in [("trend_points", "支出趋势 / Expense trend", [("balance", "Balance"), ("daily_average", "Daily average"), ("period_spend", "Period spend")]), ("forecast_points", "余额预测 / Forecast", [("projected_balance", "Projected balance"), ("total_income", "Income")])]:
                points = value.get(field, [])
                if points:
                    content.append(Chart({"title": title, "option": {"xAxis": {"type": "time"}, "yAxis": [{"name": name} for _, name in metrics], "series": [{"name": name, "type": "line", "yAxisIndex": index, "data": [[point.get("date"), point.get(metric)] for point in points]} for index, (metric, name) in enumerate(metrics)]}}))
            for sheet in value.get("sheets", []):
                exp = Gtk.Expander(label=f"{sheet.get('name', '')} · {sheet.get('row_count', len(sheet.get('rows', [])))} rows")
                exp.set_child(self.table(sheet.get("columns", []), sheet.get("rows", [])))
                content.append(exp)
            self.purchase_options = self.model_controls(content)
            self.purchase_count = Gtk.SpinButton.new_with_range(3, 30, 1)
            self.purchase_count.set_value(6)
            content.append(label(self.tr("建议数量", "Recommendation count")))
            content.append(self.purchase_count)
            actions = box(horizontal=True)
            actions.append(button(self.tr("获取采购建议（使用模型）", "Get recommendations (uses model)"), self.load_recommendations))
            actions.append(button(self.tr("重新生成", "Regenerate"), lambda: self.load_recommendations(True)))
            actions.append(button(self.tr("已隐藏建议", "Dismissed suggestions"), self.load_dismissed))
            content.append(actions)
            self.recommendations = box()
            content.append(self.recommendations)
        self.load_data("expenses", {"balance": "/api/v1/finance/balance-sheet"}, render)

    def table(self, columns, rows):
        panel = box(6)
        search = Gtk.SearchEntry(placeholder_text=self.tr("筛选行", "Filter rows"))
        panel.append(search)
        sort = Gtk.DropDown.new_from_strings([self.tr("原始顺序", "Original order"), *map(str, columns)])
        panel.append(sort)
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        header = box(horizontal=True)
        for column in columns:
            child = label(column, "title-3")
            child.set_hexpand(True)
            child.set_size_request(130, -1)
            header.append(child)
        panel.append(header)
        paging = {"offset": 0}
        status = label("")
        def populate(reset=False):
            if reset:
                paging["offset"] = 0
            clear(listing)
            term = search.get_text().lower()
            matching = []
            for values in rows:
                values = [values.get(c) for c in columns] if isinstance(values, dict) else values
                if not term or term in " ".join(scalar(v).lower() for v in values):
                    matching.append(values)
            selected = sort.get_selected() - 1
            if selected >= 0:
                matching.sort(key=lambda row: (0, row[selected]) if selected < len(row) and isinstance(row[selected], (int, float)) else (1, scalar(row[selected] if selected < len(row) else None)))
            start = paging["offset"]
            for values in matching[start:start + 100]:
                row = box(horizontal=True)
                for value in values:
                    child = label(scalar(value))
                    child.set_hexpand(True)
                    child.set_size_request(130, -1)
                    row.append(child)
                listing.append(row)
            status.set_text(f"{min(start + 1, len(matching))}–{min(start + 100, len(matching))} / {len(matching)}")
            previous.set_sensitive(start > 0)
            following.set_sensitive(start + 100 < len(matching))
        def move(offset):
            paging["offset"] = max(0, paging["offset"] + offset)
            populate()
        actions = box(horizontal=True)
        previous = button(self.tr("上一页", "Previous"), lambda: move(-100))
        following = button(self.tr("下一页", "Next"), lambda: move(100))
        actions.append(previous)
        actions.append(status)
        actions.append(following)
        panel.append(actions)
        search.connect("search-changed", lambda _: populate(True))
        sort.connect("notify::selected", lambda *_: populate(True))
        populate()
        scroll = Gtk.ScrolledWindow(min_content_height=200, max_content_height=500, propagate_natural_height=True)
        scroll.set_child(listing)
        panel.append(scroll)
        return panel

    def load_recommendations(self, regenerate=False):
        from urllib.parse import urlencode
        options = {"recommendation_count": self.purchase_count.get_value_as_int(), **self.purchase_options()}
        path = "/api/v1/finance/purchase-recommendations" + ("/regenerate" if regenerate else "?" + urlencode(options))
        def done(data):
            clear(self.recommendations)
            for group in data.get("recommendation_groups", []):
                self.recommendations.append(label(group.get("title") or group.get("name") or "Suggestions", "title-3"))
                for item in group.get("items", []):
                    row = data_view(item)
                    row.add_css_class("card")
                    payload = {"cache_key": data.get("cache_key", ""), "group_key": group.get("key") or group.get("group_key", ""), "item": item}
                    row.append(button(self.tr("隐藏", "Dismiss"), lambda payload=payload: self.dismiss_recommendation(payload)))
                    self.recommendations.append(row)
            if not data.get("recommendation_groups"):
                self.recommendations.append(data_view(data))
        self.run_async("recommendations", lambda: self.client.request(path, "POST" if regenerate else "GET", options if regenerate else None), done)

    def dismiss_recommendation(self, payload):
        self.run_async("dismiss", lambda: self.client.request("/api/v1/finance/purchase-recommendations/dismiss", "POST", payload), lambda _: self.load_recommendations())

    def load_dismissed(self):
        def done(data):
            clear(self.recommendations)
            self.recommendations.append(button(self.tr("恢复全部", "Restore all"), lambda: self.restore_recommendation()))
            for item in data.get("items", []):
                row = data_view(item)
                row.append(button(self.tr("恢复", "Restore"), lambda item=item: self.restore_recommendation(item.get("id"))))
                self.recommendations.append(row)
        self.run_async("dismissed", lambda: self.client.request("/api/v1/finance/purchase-recommendations/dismissed"), done)

    def restore_recommendation(self, item_id=None):
        suffix = f"/{item_id}" if item_id is not None else ""
        self.run_async("restore", lambda: self.client.request("/api/v1/finance/purchase-recommendations/dismissed" + suffix, "DELETE"), lambda _: self.load_dismissed())

    def load_plots(self):
        def render(data):
            content = self.heading("plots", self.tr("原生绘图 · 可调整显示范围并检查原始数据", "Native charts · adjust the range and inspect source values"))
            content.append(button(self.tr("刷新数据缓存", "Rebuild chart data"), lambda: self.run_async("refresh-plots", lambda: self.client.request("/api/v1/plots/refresh", "POST", {}), lambda _: self.load_plots())))
            for chart in data["plots"].get("charts", []):
                content.append(Chart(chart))
            if not data["plots"].get("charts"):
                content.append(label(self.tr("暂无图表数据，请检查数据目录", "No chart data; check your data directory")))
        self.load_data("plots", {"plots": "/api/v1/plots/data"}, render)

    def load_face(self):
        if self.camera_stop and not self.camera_stop.is_set():
            return
        def render(data):
            content = self.heading("face", self.tr("人脸分数不是医疗诊断；相机预览默认隐藏", "Face scores are not medical diagnoses; camera preview is hidden by default"))
            actions = box(horizontal=True)
            actions.append(button(self.tr("分析历史", "Analyze history"), self.start_face_analysis))
            actions.append(button(self.tr("导出 Excel", "Export Excel"), lambda: choose_file(self, "Export face history", self.export_face, save=True, filename="Face_Analysis_History.xlsx")))
            actions.append(button(self.tr("显示相机", "Reveal camera"), self.start_camera))
            actions.append(button(self.tr("隐藏相机", "Hide camera"), self.stop_camera))
            actions.append(button(self.tr("切换检测框", "Toggle detection"), lambda: self.run_async("detection", lambda: self.client.request("/api/v1/camera/detection/toggle", "POST", {}), lambda _: self.notice_ok(self.tr("已切换检测框", "Detection overlay changed")))))
            content.append(actions)
            self.face_progress = Gtk.ProgressBar(show_text=True)
            self.face_progress.set_fraction(max(0, min(1, data["progress"].get("percent", 0) / 100)))
            self.face_progress.set_text(data["progress"].get("status", "idle"))
            content.append(self.face_progress)
            self.camera_picture = Gtk.Picture(can_shrink=True, height_request=260)
            self.camera_picture.set_visible(False)
            content.append(self.camera_picture)
            content.append(data_view(data["status"]))
            self.face_report_box = box()
            content.append(self.face_report_box)
            self.render_face_report(data["report"])
        self.load_data("face", {"report": "/api/v1/face/report", "progress": "/api/v1/face/progress", "status": "/api/v1/system/status"}, render)

    def start_face_analysis(self):
        self.face_last_status = "starting"
        self.run_async("face-analyze", lambda: self.client.request("/api/v1/face/analyze", "POST", {}), lambda _: self.poll_face())

    def render_face_report(self, report):
        if self.page != "face" or not hasattr(self, "face_report_box"):
            return
        content = self.face_report_box
        clear(content)
        if report.get("error"):
            content.append(label(report["error"], "dim-label"))
        history = Gtk.Stack()
        switcher = Gtk.StackSwitcher(stack=history)
        content.append(switcher)
        content.append(history)
        for period, trend in report.get("trend_views", {}).items():
            chart = Chart({"title": trend.get("label", period), "option": {"xAxis": {"type": "time"}, "yAxis": {"name": "Score"}, "series": [{"name": "Face score", "type": "line", "data": [[point.get("datetime"), point.get("score")] for point in trend.get("points", [])]}]}})
            history.add_titled(chart, period, trend.get("label", period))
        for extreme in ("heaviest", "lightest"):
            record = report.get(extreme, {})
            panel = Gtk.Expander(label=f"{extreme} · {record.get('date', '')} · {record.get('score', '—')} · " + self.tr("点击显示照片", "Reveal photo"))
            picture_box = box()
            panel.set_child(picture_box)
            def revealed(widget, param, record=record, target=picture_box):
                if widget.get_expanded() and not target.get_first_child() and record.get("url"):
                    self.load_picture(record["url"], target)
            panel.connect("notify::expanded", revealed)
            content.append(panel)

    def load_picture(self, path, parent):
        picture = Gtk.Picture(can_shrink=True, height_request=240)
        parent.append(picture)
        def done(data):
            try:
                picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)))
            except GLib.Error:
                self.show_error(ClientError("Image could not be decoded"))
        self.run_async("picture-" + path, lambda: self.client.download(path), done)

    def start_camera(self):
        if self.camera_stop and not self.camera_stop.is_set():
            return
        self.camera_stop = threading.Event()
        stop = self.camera_stop
        self.camera_picture.set_visible(True)
        def worker():
            for frame in self.client.frames(stop):
                def update(frame=frame):
                    if not stop.is_set() and self.page == "face":
                        try:
                            self.camera_picture.set_paintable(Gdk.Texture.new_from_bytes(GLib.Bytes.new(frame)))
                        except GLib.Error:
                            pass
                    return False
                GLib.idle_add(update)
                time.sleep(0.04)
        self.run_async("camera", worker, on_error=lambda exc: (self.stop_camera(), self.show_error(exc)))
        self.poll_face()

    def stop_camera(self):
        if self.camera_stop:
            self.camera_stop.set()
        self.client.cancel_stream("/api/v1/camera/stream")
        if hasattr(self, "camera_picture"):
            self.camera_picture.set_paintable(None)
            self.camera_picture.set_visible(False)

    def poll_face(self):
        def done(data):
            if self.page == "face" and hasattr(self, "face_progress"):
                self.face_progress.set_fraction(max(0, min(1, data.get("percent", 0) / 100)))
                status = data.get("status", "idle")
                self.face_progress.set_text(status)
                previous, self.face_last_status = self.face_last_status, status
                if status == "done" and previous not in {None, "done"}:
                    self.run_async("face-new-report", lambda: self.client.request("/api/v1/face/report"), self.render_face_report)
                elif status == "error":
                    self.show_error(ClientError(str(data.get("error") or "Face analysis failed")))
        self.run_async("face-progress", lambda: self.client.request("/api/v1/face/progress"), done)
        if self.camera_stop and not self.camera_stop.is_set():
            self.run_async("face-live", lambda: self.client.request("/api/v1/face/live?active=true"), lambda data: self.notice_ok(f"Live face score: {data.get('latest_score', '—')}"))

    def export_face(self, path):
        self.run_async("export", lambda: self.client.download("/api/v1/face/export"), lambda data: (Path(path).write_bytes(data), self.notice_ok(self.tr("已导出", "Exported"))))

    def load_usage(self):
        def render(data):
            value = data["usage"]
            content = self.heading("usage")
            summary = value.get("summary", {})
            cards = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4, column_spacing=12, row_spacing=12)
            for field, title in [("total_tokens", "Total tokens"), ("prompt_tokens", "Input tokens"), ("completion_tokens", "Output tokens"), ("output_tokens_per_second", "Output tokens/sec"), ("prompt_cache_hit_rate", "Cache hit rate"), ("completed_call_count", "Completed calls")]:
                card = box()
                card.add_css_class("card")
                card.append(label(title, "dim-label"))
                number = summary.get(field)
                if isinstance(number, float):
                    number = f"{number:.1f}%" if field.endswith("rate") else f"{number:.2f}"
                card.append(label(scalar(number), "metric"))
                cards.append(card)
            content.append(cards)
            points = value.get("speed_series", [])
            content.append(Chart({"title": self.tr("模型吞吐速度", "Model throughput"), "option": {"xAxis": {"type": "time"}, "yAxis": {"name": "tokens/sec"}, "series": [{"name": name, "type": "line", "data": [[p.get("created_at"), p.get(field)] for p in points]} for field, name in [("average_tokens_per_second", "Total"), ("output_tokens_per_second", "Output")]]}}))
            for field, name, identity in [("by_source", "Source", "source"), ("by_day", "Daily", "date"), ("sessions", "Sessions", "session_id"), ("recent_calls", "Recent calls", "call_id")]:
                expander = Gtk.Expander(label=name)
                columns = [identity, "model", "prompt_tokens", "completion_tokens", "total_tokens", "output_tokens_per_second"]
                expander.set_child(self.table(columns, value.get(field, [])))
                content.append(expander)
        self.load_data("usage", {"usage": "/api/v1/usage"}, render)

    def load_logs(self):
        def render(data):
            content = self.heading("logs")
            search = Gtk.SearchEntry(placeholder_text=self.tr("按文本或级别过滤日志", "Filter logs by text or severity"))
            content.append(search)
            lines = data["logs"].get("logs", [])
            scroll, view = text_view("".join(lines) if any("\n" in line for line in lines) else "\n".join(lines), height=550)
            view.set_monospace(True)
            content.append(scroll)
            self.log_lines, self.log_search, self.log_view = lines, search, view
            self.logs_pause = Gtk.CheckButton(label=self.tr("暂停自动刷新", "Pause automatic refresh"))
            content.append(self.logs_pause)
            search.connect("search-changed", lambda _: self.update_logs({"logs": self.log_lines}))
            content.append(button(self.tr("复制当前日志", "Copy visible logs"), lambda: self.get_clipboard().set(buffer_text(view))))
        self.load_data("logs", {"logs": "/api/v1/system/logs"}, render)

    def update_logs(self, data):
        self.log_lines = data.get("logs", [])
        term = self.log_search.get_text().lower()
        self.log_view.get_buffer().set_text("\n".join(line.rstrip() for line in self.log_lines if term in line.lower()))

    def field(self, parent, title, value="", secret=False):
        row = box(5)
        row.append(label(title, "dim-label"))
        entry = Gtk.PasswordEntry(show_peek_icon=True) if secret else Gtk.Entry()
        entry.set_hexpand(True)
        entry.set_text(str(value or ""))
        row.append(entry)
        parent.append(row)
        return entry

    def select(self, parent, title, options, current):
        row = box(horizontal=True)
        caption = label(title)
        caption.set_hexpand(True)
        row.append(caption)
        widget = Gtk.DropDown.new_from_strings(options)
        widget.set_selected(options.index(current) if current in options else 0)
        row.append(widget)
        parent.append(row)
        return widget

    def load_settings(self):
        self.run_async("settings", lambda: self.client.request("/api/v1/settings"), self.build_settings)

    def build_settings(self, state):
        self.apply_state(state)
        content = self.heading("settings", self.tr("配置由共享后端持久化；API 密钥只写不读", "Settings are saved by the shared backend; API keys are write-only"))
        values = state.get("settings", {})
        general = box()
        general.add_css_class("card")
        general.append(label(self.tr("通用", "General"), "title-3"))
        language = self.select(general, self.tr("显示语言", "Language"), ["system", "zh-CN", "en-US"], values.get("display_language"))
        theme = self.select(general, self.tr("主题", "Theme"), ["auto", "dark", "light"], values.get("theme_mode"))
        startup = Gtk.CheckButton(label=self.tr("登录时启动", "Launch at login"), active=values.get("launch_at_login", False))
        auto = Gtk.CheckButton(label=self.tr("后端自动生成行动计划", "Backend automatic action plans"), active=values.get("action_plan_auto_generate", False))
        general.append(startup)
        general.append(auto)
        interval = Gtk.SpinButton.new_with_range(0, 35791, 1)
        interval.set_value(values.get("action_plan_check_interval_minutes", 0))
        general.append(label(self.tr("源数据检查间隔（分钟，0 关闭）", "Source check interval (minutes; 0 disables)")))
        general.append(interval)
        general.append(label(f"System locale: {system_locale()}\nGTK {Gtk.get_major_version()}.{Gtk.get_minor_version()} · Tray: {'available' if self.tray and self.tray.available else 'unavailable (close exits)'}\nMicrophone: {Path(self.recorder.tool).name if self.recorder.tool else 'use audio file upload'}", "dim-label"))
        def save_general():
            patch = {"display_language": language.get_selected_item().get_string(), "theme_mode": theme.get_selected_item().get_string(), "launch_at_login": startup.get_active(), "action_plan_auto_generate": auto.get_active(), "action_plan_check_interval_minutes": interval.get_value_as_int()}
            def work():
                self.client.request("/api/v1/settings", "PUT", patch)
                return self.client.request("/api/v1/settings")
            def saved(data):
                self.apply_state(data)
                if not self.smoke:
                    try:
                        apply_autostart(data["settings"]["launch_at_login"], self.launch_command)
                    except OSError:
                        self.show_error(ClientError("Settings saved, but login startup could not be updated; check XDG config permissions"))
                        return
                self.notice_ok(self.tr("设置已保存并重新读取验证", "Settings saved and re-read"))
                self.load_settings()
            self.run_async("save-general", work, saved)
        general.append(button(self.tr("保存通用设置", "Save general settings"), save_general, True))
        content.append(general)
        providers = state.get("provider", {}).get("providers", {})
        for route, provider in providers.items():
            self.provider_editor(content, route, provider)
        add = Gtk.Expander(label=self.tr("新增 AI 服务", "Add AI provider"))
        add_box = box()
        self.provider_editor(add_box, "", {})
        add.set_child(add_box)
        content.append(add)
        for kind in ("voice", "image"):
            panel = box()
            panel.add_css_class("card")
            panel.append(label(self.tr("语音服务" if kind == "voice" else "图像服务", kind.title() + " provider"), "title-3"))
            mode = self.select(panel, "Mode", ["inherit_ai", "custom"], values.get(f"{kind}_provider_mode"))
            endpoint = self.field(panel, "Base URL", values.get(f"{kind}_base_url"))
            key = self.field(panel, self.tr("新 API 密钥（留空保留）", "New API key (blank preserves)"), secret=True)
            erase = Gtk.CheckButton(label=self.tr("清除已保存密钥", "Clear saved key"))
            panel.append(erase)
            model = self.field(panel, "Model", values.get(f"{kind}_model"))
            result = label("")
            def fields(kind=kind, mode=mode, endpoint=endpoint, key=key, erase=erase, model=model):
                patch = {f"{kind}_provider_mode": mode.get_selected_item().get_string(), f"{kind}_base_url": endpoint.get_text(), f"{kind}_model": model.get_text()}
                if key.get_text() or erase.get_active():
                    patch[f"{kind}_api_key"] = "" if erase.get_active() else key.get_text()
                return patch
            def save_special(fields=fields, key=key):
                patch = fields()
                self.save_patch(patch, lambda _: key.set_text(""))
            panel.append(button(self.tr("保存", "Save"), save_special))
            def discover(kind=kind, fields=fields, result=result):
                values = fields()
                body = {"kind": kind, "mode": values[f"{kind}_provider_mode"], "base_url": values[f"{kind}_base_url"]}
                if f"{kind}_api_key" in values:
                    body["api_key"] = values[f"{kind}_api_key"]
                self.run_async("discover-special", lambda: self.client.request("/api/v1/providers/models/discover", "POST", body), lambda data: result.set_text(" · ".join(data.get("models", []))))
            panel.append(button(self.tr("发现模型", "Discover models"), discover))
            panel.append(result)
            content.append(panel)
        advanced = Gtk.Expander(label=self.tr("高级模型参数", "Advanced model parameters"))
        advanced_box = box()
        scroll, editor = text_view(json.dumps({k: state.get("provider", {}).get(k, {}) for k in ("sampling_defaults", "model_profiles")}, ensure_ascii=False, indent=2), editable=True, height=220)
        advanced_box.append(scroll)
        def save_advanced():
            try:
                config = json.loads(buffer_text(editor))
                if not isinstance(config, dict) or set(config) - {"sampling_defaults", "model_profiles"}:
                    raise ValueError()
                self.save_patch({"provider_config": config})
            except ValueError:
                self.show_error(ClientError("Use a JSON object containing sampling_defaults and model_profiles only"))
        advanced_box.append(button(self.tr("保存模型参数", "Save model parameters"), save_advanced))
        advanced.set_child(advanced_box)
        content.append(advanced)
        paths = box()
        paths.append(label(self.tr("数据与日志", "Data & logs"), "title-3"))
        for key, path in state.get("runtime_paths", {}).items():
            if key in {"config", "history", "logs", "plots", "cache", "runtime", "data", "config_dir", "history_dir", "log_dir", "plot_dir", "cache_dir", "runtime_dir", "data_dir"} and isinstance(path, str):
                row = box(horizontal=True)
                value = label(f"{key}: {path}")
                value.set_hexpand(True)
                row.append(value)
                row.append(button(self.tr("打开", "Open"), lambda path=path: self.open_path(path)))
                paths.append(row)
        content.append(paths)

    def provider_editor(self, parent, route, provider):
        panel = box()
        panel.add_css_class("card")
        panel.append(label(provider.get("name") or route or self.tr("新增服务", "New provider"), "title-3"))
        route_field = self.field(panel, "Route", route)
        route_field.set_editable(not bool(route))
        name = self.field(panel, self.tr("名称", "Name"), provider.get("name"))
        url = self.field(panel, "Base URL", provider.get("base_url"))
        key = self.field(panel, self.tr("新 API 密钥（留空保留）", "New API key (blank preserves)"), secret=True)
        key.set_property("placeholder-text", self.tr("已有密钥" if provider.get("api_key") else "未设置", "Saved key" if provider.get("api_key") else "Not configured"))
        erase = Gtk.CheckButton(label=self.tr("明确清除密钥", "Explicitly clear key"))
        panel.append(erase)
        model = self.field(panel, "Model", provider.get("model"))
        catalog = self.field(panel, self.tr("模型列表（逗号分隔）", "Model catalog (comma-separated)"), ", ".join(provider.get("models", [])))
        refreshed = {"value": provider.get("last_refreshed_at")}
        enabled = Gtk.CheckButton(label=self.tr("启用", "Enabled"), active=provider.get("enabled", True))
        panel.append(enabled)
        result = label("")
        def payload():
            return {"name": name.get_text(), "base_url": url.get_text().strip(), "model": model.get_text().strip(), "models": list(dict.fromkeys([item.strip() for item in catalog.get_text().split(",") if item.strip()] + ([model.get_text().strip()] if model.get_text().strip() else []))), "last_refreshed_at": refreshed["value"], "enabled": enabled.get_active()}
        def save():
            selected = route_field.get_text().strip()
            values = payload()
            secret = key.get_text()
            def work():
                current = self.client.request("/api/v1/settings")
                patch = provider_patch(current, selected, values, secret, erase.get_active())
                self.client.request("/api/v1/settings", "PUT", patch)
                return self.client.request("/api/v1/settings")
            def saved(data):
                key.set_text("")
                self.apply_state(data)
                self.notice_ok(self.tr("服务配置已保存并验证", "Provider configuration saved and re-read"))
                self.load_settings()
            self.run_async("save-provider", work, saved)
        panel.append(button(self.tr("保存并选用", "Save & select"), save, True))
        def discover():
            request = {"route": route_field.get_text(), "base_url": url.get_text(), "type": "openai-compatible"}
            if key.get_text():
                request["api_key"] = key.get_text()
            def discovered(data):
                from datetime import datetime, timezone
                models = data.get("models", [])
                catalog.set_text(", ".join(models))
                refreshed["value"] = data.get("last_refreshed_at") or datetime.now(timezone.utc).isoformat()
                result.set_text(self.tr("已发现；点击保存持久化", "Discovered; click Save to persist") + " · " + " · ".join(models))
            self.run_async("discover-models", lambda: self.client.request("/api/v1/models/discover", "POST", request), discovered)
        panel.append(button(self.tr("发现模型", "Discover models"), discover))
        panel.append(result)
        if route:
            def remove():
                def work():
                    current = self.client.request("/api/v1/settings")
                    providers = current.get("provider", {}).get("providers", {})
                    providers.pop(route, None)
                    for entry in providers.values():
                        entry.pop("api_key", None)
                    selected = current.get("provider", {}).get("selected_provider")
                    patch = {"providers": providers}
                    if selected == route:
                        patch["selected_provider"] = next(iter(providers), None)
                    self.client.request("/api/v1/settings", "PUT", {"provider_config": patch})
                    return self.client.request("/api/v1/settings")
                self.run_async("delete-provider", work, lambda state: (self.apply_state(state), self.load_settings()))
            panel.append(button(self.tr("删除服务", "Delete provider"), lambda: self.confirm(self.tr("删除此 AI 服务及其已保存密钥？", "Delete this provider and its saved key?"), remove)))
        parent.append(panel)

    def save_patch(self, patch, extra=None):
        def work():
            self.client.request("/api/v1/settings", "PUT", patch)
            return self.client.request("/api/v1/settings")
        def done(state):
            self.apply_state(state)
            if extra:
                extra(state)
            self.notice_ok(self.tr("已保存并重新读取", "Saved and re-read"))
        self.run_async("save-patch", work, done)

    def open_path(self, path):
        try:
            open_folder(path)
        except (RuntimeError, GLib.Error) as exc:
            self.show_error(ClientError(str(exc)))

    def build_onboarding(self):
        content = self.pages["onboarding"]
        clear(content)
        content.append(label(self.tr("欢迎使用 Vantage", "Welcome to Vantage"), "title-1"))
        content.append(label(self.tr("连接 AI 服务后可生成计划并聊天，也可以稍后设置。", "Connect an AI provider for plans and chat, or configure it later.")))
        language = self.select(content, "Language / 语言", ["system", "zh-CN", "en-US"], self.state.get("settings", {}).get("display_language"))
        route = self.field(content, "Provider route", "custom")
        endpoint = self.field(content, "Base URL")
        key = self.field(content, "API key", secret=True)
        model = self.field(content, "Model")
        startup = Gtk.CheckButton(label=self.tr("登录时启动", "Launch at login"))
        content.append(startup)
        result = label("")
        content.append(result)
        def complete(skip):
            request = {"skip_chat_setup": skip, "display_language": language.get_selected_item().get_string(), "launch_at_login": startup.get_active()}
            if not skip:
                if not route.get_text().strip():
                    self.show_error(ClientError("Provider route is required"))
                    return
                request.update(selected_provider=route.get_text().strip(), base_url=endpoint.get_text(), api_key=key.get_text(), model=model.get_text())
            def work():
                self.client.request("/api/v1/onboarding/complete", "POST", request)
                return self.client.request("/api/v1/settings")
            def done(state):
                key.set_text("")
                self.apply_state(state)
                if not state.get("settings", {}).get("onboarding_completed"):
                    self.show_error(ClientError("Onboarding did not persist; try again"))
                    return
                if not self.smoke:
                    try:
                        apply_autostart(state["settings"].get("launch_at_login", False), self.launch_command)
                    except OSError:
                        self.show_error(ClientError("Onboarding saved, but login startup could not be applied"))
                self.nav.set_sensitive(True)
                self.navigate("dashboard")
                self.connect_backend()
            self.run_async("onboarding", work, done)
        actions = box(horizontal=True)
        actions.append(button(self.tr("保存并开始", "Save & start"), lambda: complete(False), True))
        actions.append(button(self.tr("暂时跳过 AI 配置", "Skip AI setup for now"), lambda: complete(True)))
        content.append(actions)

    def confirm(self, text, action):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, text=text, buttons=Gtk.ButtonsType.OK_CANCEL)
        def response(dialog, code):
            dialog.destroy()
            if code == Gtk.ResponseType.OK:
                action()
        dialog.connect("response", response)
        dialog.present()

    def poll(self):
        if self.closed:
            return GLib.SOURCE_REMOVE
        if self.connected and self.page == "face":
            self.poll_face()
        if self.connected and self.page == "dashboard" and hasattr(self, "dashboard_metrics"):
            def metrics(data):
                for name, field, unit in [("CPU", "cpu_usage", "%"), (self.tr("内存", "Memory"), "memory_used_gb", " GB"), (self.tr("可用磁盘", "Free disk"), "disk_free_gb", " GB")]:
                    if name in self.dashboard_metrics:
                        self.dashboard_metrics[name].set_text(f"{data.get(field, '—')}{unit}")
            self.run_async("dashboard-live", lambda: self.client.request("/api/v1/system/statistics"), metrics)
        if self.connected and (not self.job_observer or self.job_observer.stop.is_set()):
            self.discover_job()
            if self.page in {"plan", "dashboard"}:
                self.run_async("saved-plan", lambda: self.client.request("/api/v1/action-plan/today"), self.update_saved_plan)
        if self.connected and self.page == "logs" and hasattr(self, "logs_pause") and not self.logs_pause.get_active():
            self.run_async("logs-poll", lambda: self.client.request("/api/v1/system/logs"), self.update_logs)
        return GLib.SOURCE_CONTINUE

    def update_saved_plan(self, result):
        identity = (result.get("id"), result.get("filename"), result.get("timestamp"))
        if identity == self.last_plan_identity or not complete_result(result):
            return
        self.last_plan_identity = identity
        if self.job_observer and not self.job_observer.stop.is_set():
            return
        if self.page == "plan" and hasattr(self, "plan_plan_view"):
            for section in ("analysis", "plan"):
                set_view_text(getattr(self, f"plan_{section}_view"), result[section]["body"])
        elif self.page == "dashboard" and hasattr(self, "dashboard_plan"):
            set_view_text(self.dashboard_plan, result["plan"]["body"])

    def close_requested(self, *_):
        if self.tray and self.tray.available:
            self.hide()
            self.stop_camera()
            self.stop_chat()
            self.recorder.discard()
            return True
        self.quit_app()
        return True

    def quit_app(self):
        if self.closed:
            return
        self.closed = True
        if self.job_observer:
            self.job_observer.stop.set()
        self.stop_chat()
        self.stop_camera()
        self.recorder.discard()
        self.pool.shutdown(wait=False, cancel_futures=True)
        # An attached backend belongs to its existing host and is left running.
        self.host.close()
        self.get_application().quit()


class Application(Gtk.Application):
    def __init__(self, host, launch_command, smoke=False):
        flags = Gio.ApplicationFlags.NON_UNIQUE if smoke else Gio.ApplicationFlags.DEFAULT_FLAGS
        super().__init__(application_id="org.vantage.Native", flags=flags)
        self.host = host
        self.launch_command = launch_command
        self.smoke = smoke
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", lambda *_: self.window.quit_app() if self.window else self.quit())
        self.add_action(action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def do_activate(self):
        if self.window is None:
            self.window = Window(self, self.host, self.launch_command, smoke=self.smoke)
        self.window.present()
