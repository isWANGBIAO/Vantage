"""Pure chart coordinate preparation, tested without GTK/display dependencies."""
from datetime import datetime, timezone
import math


def numeric(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def time_value(value):
    if numeric(value):
        return float(value) / 1000  # ECharts timestamps are milliseconds.
    try:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date.timestamp()
    except (ValueError, OverflowError):
        return None


def series_points(series, categories=None):
    points = []
    for i, point in enumerate(series.get("data", [])):
        if isinstance(point, dict):
            point = point.get("value")
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            x, y = point[0], point[1]
        else:
            x, y = (categories[i] if categories and i < len(categories) else i + 1), point
        points.append((x, float(y) if numeric(y) else None))
    return points


def prepare_chart(option, limit=90):
    xaxis = option.get("xAxis", {})
    xaxis = xaxis[0] if isinstance(xaxis, list) and xaxis else xaxis
    axes = option.get("yAxis", {})
    axes = axes if isinstance(axes, list) else [axes]
    axes = axes or [{}]
    categories = xaxis.get("data", [])
    prepared = [{"source": series, "axis": int(series.get("yAxisIndex", 0)), "points": series_points(series, categories)[-limit:]} for series in option.get("series", [])]
    keys = list(dict.fromkeys(key for series in prepared for key, _ in series["points"]))
    if xaxis.get("type") == "time":
        keys.sort(key=lambda k: time_value(k) or 0)
        xvalues = {key: time_value(key) for key in keys}
    elif xaxis.get("type") == "value":
        xvalues = {key: float(key) if str(key).replace(".", "", 1).replace("-", "", 1).isdigit() else None for key in keys}
    else:
        xvalues = {key: float(i) for i, key in enumerate(keys)}
    valid_x = [v for v in xvalues.values() if v is not None]
    xmin, xmax = (min(valid_x), max(valid_x)) if valid_x else (0, 1)
    if xmin == xmax:
        xmax = xmin + 1
    while len(axes) <= max((s["axis"] for s in prepared), default=0):
        axes.append({})
    axis_values = [[] for _ in axes]
    stacks = {}
    bar_groups = []
    for series in prepared:
        source = series["source"]
        axis = series["axis"]
        group = (axis, source.get("stack") or f"unstacked-{len(bar_groups)}")
        if source.get("type") == "bar" and group not in bar_groups:
            bar_groups.append(group)
        series["bar_group"] = group
        series["coordinates"] = []
        for key, value in series["points"]:
            baseline = 0.0
            if value is not None and source.get("stack"):
                stack_key = (axis, source["stack"], key, "positive" if value >= 0 else "negative")
                baseline = stacks.get(stack_key, 0.0)
                stacks[stack_key] = baseline + value
            top = baseline + value if value is not None else None
            series["coordinates"].append({"key": key, "x": xvalues.get(key), "value": value, "y": top, "base": baseline})
            if top is not None:
                axis_values[axis].append(top)
                if source.get("type") == "bar":
                    axis_values[axis].append(baseline)
    scales = []
    for axis, values in zip(axes, axis_values):
        vmin, vmax = (min(values), max(values)) if values else (0.0, 1.0)
        lo = axis.get("min", min(0.0, vmin))
        hi = axis.get("max", max(0.0, vmax))
        lo = vmin if lo == "dataMin" else float(lo) if numeric(lo) else min(0.0, vmin)
        hi = vmax if hi == "dataMax" else float(hi) if numeric(hi) else max(0.0, vmax)
        if hi == lo:
            hi += 1
        scales.append({"min": lo, "max": hi, "inverse": bool(axis.get("inverse")), "name": axis.get("name", "")})
    return {"series": prepared, "axes": scales, "xmin": xmin, "xmax": xmax, "keys": keys, "bar_groups": bar_groups}


def normalized_y(value, axis):
    normalized = (value - axis["min"]) / (axis["max"] - axis["min"])
    return normalized if axis["inverse"] else 1.0 - normalized
