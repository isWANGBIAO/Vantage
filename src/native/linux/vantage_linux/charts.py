"""Native Cairo rendering of backend chart series (no embedded browser)."""
import math
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

COLORS = [(0.27, 0.79, 0.69), (0.51, 0.65, 1), (0.98, 0.70, 0.35), (0.85, 0.48, 0.70), (0.60, 0.80, 0.39)]


from .chart_data import numeric, series_points, prepare_chart, normalized_y


class Chart(Gtk.Box):
    def __init__(self, spec):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.spec = spec
        self.option = spec.get("option", {})
        self.limit = 90
        self.add_css_class("card")
        label = Gtk.Label(label=spec.get("title", "Chart"), xalign=0)
        label.add_css_class("title-3")
        self.append(label)
        description = Gtk.Label(label=spec.get("description", ""), xalign=0, wrap=True)
        description.add_css_class("dim-label")
        self.append(description)
        controls = Gtk.Box(spacing=8)
        controls.append(Gtk.Label(label="显示点数 / Points"))
        count = Gtk.SpinButton.new_with_range(5, 10000, 5)
        count.set_value(self.limit)
        count.connect("value-changed", lambda widget: self.change_limit(widget.get_value_as_int()))
        controls.append(count)
        self.append(controls)
        self.area = Gtk.DrawingArea(content_width=620, content_height=280, hexpand=True)
        self.area.set_draw_func(self.draw)
        self.append(self.area)
        self.legend = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.append(self.legend)
        if spec.get("error") or spec.get("empty"):
            self.legend.set_text(str(spec.get("error") or "没有可显示的数据 / No data"))
        else:
            self.legend.set_text("   ·   ".join(str(s.get("name", "Series")) for s in self.option.get("series", [])))
        details = Gtk.Expander(label="检查数据 / Inspect values")
        text = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.NONE)
        axis = self.option.get("xAxis", {})
        axis = axis[0] if isinstance(axis, list) and axis else axis
        categories = axis.get("data", []) if isinstance(axis, dict) else []
        lines = []
        for series in self.option.get("series", []):
            lines.append(str(series.get("name", "Series")))
            lines.extend(f"  {x}\t{y if y is not None else '—'}" for x, y in series_points(series, categories))
        text.get_buffer().set_text("\n".join(lines))
        scroll = Gtk.ScrolledWindow(min_content_height=180, max_content_height=300)
        scroll.set_child(text)
        details.set_child(scroll)
        self.append(details)

    def change_limit(self, limit):
        self.limit = limit
        self.area.queue_draw()

    def draw(self, area, cr, width, height):
        cr.set_source_rgb(0.08, 0.10, 0.13)
        cr.paint()
        series_list = self.option.get("series", [])
        if not series_list:
            return
        if any(s.get("type") == "radar" for s in series_list):
            return self.draw_radar(cr, width, height, series_list)
        prepared = prepare_chart(self.option, self.limit)
        left, right, top, bottom = 65, width - 35 - 45 * max(0, len(prepared["axes"]) - 1), 25, height - 38
        x = lambda value: left + (value - prepared["xmin"]) / (prepared["xmax"] - prepared["xmin"]) * (right - left)
        y = lambda value, axis: top + normalized_y(value, axis) * (bottom - top)
        cr.set_font_size(10)
        for index, axis in enumerate(prepared["axes"]):
            for tick in range(5):
                val = axis["min"] + (axis["max"] - axis["min"]) * tick / 4
                pos = y(val, axis)
                cr.set_source_rgb(0.20, 0.23, 0.27)
                if index == 0:
                    cr.move_to(left, pos)
                    cr.line_to(right, pos)
                    cr.stroke()
                cr.set_source_rgb(*COLORS[index % len(COLORS)])
                cr.move_to(5 if index == 0 else right + 8 + (index - 1) * 45, pos + 4)
                cr.show_text(f"{val:.1f}")
            cr.move_to(5 if index == 0 else right + 5 + (index - 1) * 45, 12)
            cr.show_text(str(axis["name"])[:12])
        if prepared["keys"]:
            cr.set_source_rgb(0.65, 0.70, 0.75)
            for key, pos in [(prepared["keys"][0], left), (prepared["keys"][-1], right - 65)]:
                cr.move_to(pos, height - 12)
                cr.show_text(key[:16])
        groups = prepared["bar_groups"]
        cr.save()
        cr.rectangle(left - 15, top, right - left + 30, bottom - top)
        cr.clip()
        for index, series in enumerate(prepared["series"]):
            cr.set_source_rgb(*COLORS[index % len(COLORS)])
            cr.set_line_width(2)
            kind = series["source"].get("type", "line")
            axis = prepared["axes"][series["axis"]]
            begun = False
            for point in series["coordinates"]:
                if point["y"] is None or point["x"] is None:
                    if begun and not series["source"].get("connectNulls", False):
                        cr.stroke()
                        begun = False
                    continue
                px, py = x(point["x"]), y(point["y"], axis)
                if kind == "bar":
                    count = max(1, len(prepared["keys"]))
                    bw = max(1, min(30, (right - left) / count / (len(groups) + 1)))
                    offset = groups.index(series["bar_group"]) - len(groups) / 2
                    base = y(point["base"], axis)
                    cr.rectangle(px + offset * bw, min(py, base), bw, max(1, abs(base - py)))
                    cr.fill()
                elif kind == "scatter":
                    cr.arc(px, py, 3, 0, math.tau)
                    cr.fill()
                else:
                    (cr.line_to if begun else cr.move_to)(px, py)
                    begun = True
            cr.stroke()
        cr.restore()

    def draw_radar(self, cr, width, height, series_list):
        radar = self.option.get("radar", {})
        radar = radar[0] if isinstance(radar, list) and radar else radar
        indicators = radar.get("indicator", [])
        n = len(indicators)
        if n < 3:
            return
        center = (width / 2, height / 2)
        radius = min(width, height) * 0.35
        for i in range(n):
            angle = math.tau * i / n - math.pi / 2
            cr.set_source_rgb(0.35, 0.40, 0.45)
            cr.move_to(*center)
            cr.line_to(center[0] + radius * math.cos(angle), center[1] + radius * math.sin(angle))
            cr.stroke()
            cr.move_to(center[0] + radius * 1.05 * math.cos(angle), center[1] + radius * 1.05 * math.sin(angle))
            cr.show_text(str(indicators[i].get("name", ""))[:18])
        color_index = 0
        for index, series in enumerate(series_list):
            for point in series.get("data", []):
                vals = point.get("value", []) if isinstance(point, dict) else point
                if not isinstance(vals, list):
                    continue
                cr.set_source_rgb(*COLORS[color_index % len(COLORS)])
                cr.move_to(8, 15 + color_index * 16)
                cr.show_text(str(point.get("name", series.get("name", "")))[:25])
                color_index += 1
                for i, value in enumerate(vals[:n]):
                    angle = math.tau * i / n - math.pi / 2
                    ratio = float(value) / max(1, float(indicators[i].get("max", 100))) if numeric(value) else 0
                    xy = (center[0] + radius * ratio * math.cos(angle), center[1] + radius * ratio * math.sin(angle))
                    (cr.move_to if i == 0 else cr.line_to)(*xy)
                cr.close_path()
                cr.stroke()
