import os
import platform
import re
import shutil
import tempfile
import subprocess
import math
import glob
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scienceplots
from matplotlib import rcParams
from matplotlib.ticker import FuncFormatter
from matplotlib.ticker import MaxNLocator
from PIL import Image
from src.utils.data_loader import DataLoader

COLORS = {
    "blue": "#2F6FED",
    "orange": "#F28E2B",
    "green": "#59A14F",
    "red": "#E15759",
    "purple": "#B07AA1",
    "gray": "#6B7280",
    "lightblue": "#9AD0F5",
}


def configure_matplotlib(is_dark_mode=False):
    plt.style.use(["nature", "no-latex"])

    font_family = pick_font_family()
    if font_family:
        available = get_available_fonts()
        fallback = ["DejaVu Sans"]
        if "Times New Roman" in available:
            fallback = ["Times New Roman"] + fallback
        plt.rcParams["font.family"] = [font_family] + fallback
        plt.rcParams["font.sans-serif"] = [font_family] + fallback
    else:
        plt.rcParams["font.family"] = ["DejaVu Sans"]
        plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]

    plt.rcParams["axes.unicode_minus"] = False
    rcParams["font.size"] = 18
    rcParams["axes.labelsize"] = 18
    rcParams["xtick.labelsize"] = 18
    rcParams["ytick.labelsize"] = 18
    rcParams["legend.fontsize"] = 18
    rcParams["axes.titlesize"] = 18
    rcParams["axes.titleweight"] = "bold"
    rcParams["grid.alpha"] = 0.3
    rcParams["grid.linestyle"] = "--"
    rcParams["grid.linewidth"] = 0.6
    rcParams["lines.linewidth"] = 1.8
    rcParams["lines.markersize"] = 4
    rcParams["legend.frameon"] = False
    plt.rcParams["figure.figsize"] = [12, 12]

    if is_dark_mode:
        # Dark Mode Overrides
        rcParams["figure.facecolor"] = "#2b2b2b"
        rcParams["axes.facecolor"] = "#2b2b2b"
        rcParams["savefig.facecolor"] = "#2b2b2b"
        
        rcParams["text.color"] = "white"
        rcParams["axes.labelcolor"] = "white"
        rcParams["xtick.color"] = "white"
        rcParams["ytick.color"] = "white"
        rcParams["axes.edgecolor"] = "#555555"
        rcParams["grid.color"] = "#555555"
        rcParams["figure.edgecolor"] = "#2b2b2b"
        
        # Adjust colors for visibility on dark background
        COLORS["blue"] = "#5e96ff"
        COLORS["orange"] = "#ffb066"
        COLORS["green"] = "#8cd98c"
        COLORS["red"] = "#ff8c8e"
        COLORS["purple"] = "#d1a3ff"
        COLORS["gray"] = "#a0a0a0"
        COLORS["lightblue"] = "#b3e0ff"
    else:
        # Restore Light Mode Defaults (or just don't override)
        # We need to reset these if switching back and forth in same process
        rcParams["figure.facecolor"] = "white"
        rcParams["axes.facecolor"] = "white"
        rcParams["savefig.facecolor"] = "white"
        
        rcParams["text.color"] = "black"
        rcParams["axes.labelcolor"] = "black"
        rcParams["xtick.color"] = "black"
        rcParams["ytick.color"] = "black"
        rcParams["axes.edgecolor"] = "black"
        rcParams["grid.color"] = "#b0b0b0"
        
        # Restore standard colors
        COLORS["blue"] = "#2F6FED"
        COLORS["orange"] = "#F28E2B"
        COLORS["green"] = "#59A14F"
        COLORS["red"] = "#E15759"
        COLORS["purple"] = "#B07AA1"
        COLORS["gray"] = "#6B7280"
        COLORS["lightblue"] = "#9AD0F5"


def load_excel_safely(path):
    """Safely load Excel file even if it is open/locked by copying to temp first."""
    path = str(path)
    try:
        return pd.read_excel(path, engine="openpyxl")
    except PermissionError:
        print(f"Warning: File {path} is locked. Attempting to copy to temp...")
        try:
            # Create temp file path
            fd, temp_path = tempfile.mkstemp(suffix=".xlsx")
            os.close(fd)
            
            # Try shutil copy
            try:
                shutil.copy2(path, temp_path)
            except PermissionError:
                # Fallback to PowerShell Copy-Item (Win32 API based copy often works on locked files)
                cmd = ["powershell", "-NoProfile", "-Command", f"Copy-Item -LiteralPath '{path}' -Destination '{temp_path}' -Force"]
                subprocess.run(cmd, check=True, capture_output=True)
            
            # Read from temp
            df = pd.read_excel(temp_path, engine="openpyxl")
            
            # Cleanup
            try:
                os.remove(temp_path)
            except:
                pass
            
            return df
        except Exception as e:
            print(f"Failed to copy and read locked file: {e}")
            raise



def get_project_root():
    """Dynamically find project root by looking for .env or requirements.txt"""
    # Start from current file path and go up
    current = Path(__file__).resolve().parent
    for _ in range(5): # Check up to 5 levels up
        if (current / ".env").exists() or (current / "requirements.txt").exists():
             return current
        current = current.parent
    return Path.cwd() # Fallback

def resolve_data_root(user_home=None, onedrive_env=None):
    return DataLoader.resolve_data_root(user_home=user_home, onedrive_env=onedrive_env)


def resolve_data_path(filename, user_home=None, onedrive_env=None):
    return DataLoader.resolve_data_path(filename, user_home=user_home, onedrive_env=onedrive_env)


def register_font_files():
    candidates = []
    font_dirs = [
        Path(r"C:\Windows\Fonts"),
        Path("/mnt/c/Windows/Fonts"),
    ]
    font_files = [
        "msyh.ttc",
        "msyhbd.ttc",
        "msyh.ttf",
        "simsun.ttc",
        "simsunb.ttf",
        "simhei.ttf",
        "simkai.ttf",
        "simfang.ttf",
    ]
    for font_dir in font_dirs:
        for font_file in font_files:
            path = font_dir / font_file
            if path.exists():
                candidates.append(path)

    linux_candidates = [
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK.ttc"),
        Path("/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/arphic/uming.ttc"),
    ]
    for path in linux_candidates:
        if path.exists():
            candidates.append(path)

    font_names = []
    for path in candidates:
        try:
            fm.fontManager.addfont(str(path))
            name = fm.FontProperties(fname=str(path)).get_name()
            font_names.append(name)
        except Exception:
            continue
    return font_names


def get_available_fonts():
    return {font.name for font in fm.fontManager.ttflist}


def pick_font_family():
    registered = register_font_files()
    available = get_available_fonts()
    system = platform.system()

    if system == "Windows":
        preferred = [
            "Microsoft YaHei",
            "SimSun",
            "SimHei",
            "KaiTi",
            "FangSong",
            "Arial Unicode MS",
        ]
    elif system == "Darwin":
        preferred = [
            "PingFang SC",
            "Heiti SC",
            "STHeiti",
            "Songti SC",
            "Arial Unicode MS",
        ]
    else:
        preferred = [
            "Microsoft YaHei",
            "SimSun",
            "SimHei",
            "Noto Sans CJK SC",
            "Noto Sans CJK",
            "Source Han Sans SC",
            "WenQuanYi Zen Hei",
            "AR PL UMing CN",
            "AR PL UKai CN",
        ]

    for name in preferred + registered:
        if name in available:
            return name
    return None


def resolve_output_dir():
    env_root = os.environ.get("AI_PLOT_OUTPUT_DIR") or os.environ.get("PLOT_OUTPUT_DIR")
    if env_root:
        root = Path(env_root)
    else:
        root = get_project_root() / "plot_outputs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_collage_size():
    width = os.environ.get("PLOT_COLLAGE_WIDTH") or os.environ.get("PLOT_SCREEN_WIDTH")
    height = os.environ.get("PLOT_COLLAGE_HEIGHT") or os.environ.get("PLOT_SCREEN_HEIGHT")
    if width is None or height is None:
        return 5120, 2880  # 5K resolution for high DPI clarity
    try:
        return int(width), int(height)
    except ValueError:
        return 5120, 2880


def save_figure(fig, output_dir, filename):
    if output_dir is None:
        output_dir = resolve_output_dir()
    if not filename.lower().endswith(".png"):
        filename = f"{filename}.png"
    path = Path(output_dir) / filename
    fig.savefig(path, dpi=800, bbox_inches='tight', pad_inches=0.1, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    return path


def format_date_axis(ax, days):
    if days > 365:
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    elif days > 120:
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    elif days > 45:
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MONDAY, interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    else:
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))


def apply_axis_style(ax, grid_axis="both"):
    ax.grid(True, axis=grid_axis)
    ax.spines["top"].set_visible(False)


def format_hours_label(hours):
    if hours is None or np.isnan(hours):
        return "--"
    hour = int(hours)
    minute = int(round((hours - hour) * 60))
    return f"{hour}h{minute:02d}m"


def get_figsize(_kind=None, _days=None):
    width = os.environ.get("PLOT_FIG_WIDTH")
    height = os.environ.get("PLOT_FIG_HEIGHT")
    if width is None or height is None:
        return (16, 9)
    try:
        return (float(width), float(height))
    except ValueError:
        return (16, 9)


def _collect_plot_images(output_dir):
    output_dir = Path(output_dir)
    files = sorted(output_dir.glob("*.png"))
    return [
        path
        for path in files
        if not path.name.endswith("_screen.png")
        and not path.name.startswith("plot_collage")
    ]


def merge_plot_images(output_dir, filename="plot_collage.png", is_dark_mode=False):
    output_dir = Path(output_dir)
    files = _collect_plot_images(output_dir)
    if not files:
        print("未找到可合并的图片")
        return None

    collage_width, collage_height = get_collage_size()
    aspect = collage_width / collage_height
    total = len(files)
    order = [
        "weight_bodyfat",
        "time_allocation_bar",
        "time_trend_screen_remaining",
        "time_trend_averages",
        "time_trend_delta",
        "running_pace",
        "radar_goal",
        "hhh_frequency",
        "hhh_interval_trend",
        "balance_sheet",
    ]

    def sort_key(path):
        name = path.stem
        for index, prefix in enumerate(order):
            if name.startswith(prefix):
                return (index, name)
        return (len(order), name)

    files = sorted(files, key=sort_key)
    files = sorted(files, key=sort_key)
    cols = 5
    rows = math.ceil(len(files) / cols) if len(files) > 0 else 1
    padding = max(16, int(min(collage_width, collage_height) * 0.01))
    cell_width = max(1, (collage_width - padding * (cols + 1)) // cols)
    cell_height = max(1, (collage_height - padding * (rows + 1)) // rows)

    bg_color = (43, 43, 43) if is_dark_mode else (250, 250, 250)
    background = Image.new("RGB", (collage_width, collage_height), bg_color)
    for index, path in enumerate(files):
        image = Image.open(path).convert("RGB")
        image.thumbnail((cell_width, cell_height), Image.LANCZOS)
        x = padding + (index % cols) * (cell_width + padding) + (cell_width - image.width) // 2
        y = padding + (index // cols) * (cell_height + padding) + (cell_height - image.height) // 2
        background.paste(image, (x, y))

    output_path = output_dir / filename
    background.save(output_path, "PNG", optimize=True)
    print(f"已生成合并图: {output_path} (分辨率: {collage_width}x{collage_height})")
    return output_path


def _format_time_error_location(row_index, column_name):
    if row_index is None:
        return ""
    if isinstance(row_index, (int, np.integer)):
        excel_row = row_index + 2
        location = f"（行号: {row_index}, Excel行: {excel_row}"
    else:
        location = f"（行号: {row_index}"
    if column_name:
        location += f", 列: {column_name}"
    location += "）"
    return location


def time_to_hour(time_value, row_index=None, column_name=None):
    if pd.isna(time_value):
        return None
    pattern = r"(?:(\d+)小时)(?:(\d+)分)?"
    match = re.search(pattern, str(time_value))
    if match:
        hours = int(match.group(1)) if match.group(1) else 0
        minutes = int(match.group(2)) if match.group(2) else 0
        total_hours = hours + minutes / 60.0
        if total_hours > 24 or total_hours < 0:
            location = _format_time_error_location(row_index, column_name)
            print("时间格式错误：", time_value, location)
            return None
        return total_hours
    location = _format_time_error_location(row_index, column_name)
    print("时间格式错误：", time_value, location)
    return None


def load_time_data(path=None):
    if path is None:
        path = resolve_data_path("Time.xlsx")
    return load_excel_safely(path)


def plot_weight_and_body_fat_rate(data_frame, recent_days=30, output_dir=None):
    fig, ax1 = plt.subplots(figsize=get_figsize("weight", recent_days))

    filtered_df_weight = data_frame.dropna(subset=["体重"])
    if filtered_df_weight.empty:
        raise ValueError("体重数据为空，无法绘图")

    if recent_days > len(filtered_df_weight):
        recent_days = len(filtered_df_weight)

    valid_weight_y = filtered_df_weight["体重"].to_numpy()
    average_weight = np.average(valid_weight_y)
    lns1 = ax1.plot(
        filtered_df_weight["日期"],
        valid_weight_y,
        "-",
        label="体重",
        color=COLORS["blue"],
        linewidth=2.0,
        alpha=0.85,
    )
    ax1.plot(
        filtered_df_weight["日期"],
        np.full_like(valid_weight_y, average_weight),
        "--",
        label=f"平均体重 {round(average_weight, 2)}kg",
        color=COLORS["blue"],
        alpha=0.6,
        linewidth=1.4,
    )
    ax1.set_ylabel("体重(kg)", color=COLORS["blue"])
    ax1.tick_params(axis="y", labelcolor=COLORS["blue"])
    ax1.set_xlim(
        filtered_df_weight["日期"].iloc[-recent_days],
        filtered_df_weight["日期"].iloc[-1],
    )

    recent_weight_y = filtered_df_weight["体重"].iloc[-recent_days:].to_numpy()
    ax1.set_ylim(recent_weight_y.min() - 1, recent_weight_y.max() + 1)

    lns2 = []
    lns3 = []

    filtered_df_fat = data_frame.dropna(subset=["体脂率"])
    if not filtered_df_fat.empty:
        valid_body_fat_rate_y = filtered_df_fat["体脂率"].to_numpy()
        average_body_fat_rate = np.average(valid_body_fat_rate_y)
        ax2 = ax1.twinx()
        lns2 = ax2.plot(
            filtered_df_fat["日期"],
            valid_body_fat_rate_y,
            "-",
            label="体脂率",
            color=COLORS["orange"],
            linewidth=1.8,
            alpha=0.85,
        )
        ax2.plot(
            filtered_df_fat["日期"],
            np.full_like(valid_body_fat_rate_y, average_body_fat_rate),
            "--",
            label=f"平均体脂率 {round(average_body_fat_rate)}%",
            color=COLORS["orange"],
            alpha=0.6,
            linewidth=1.4,
        )
        ax2.set_ylabel("体脂率(%)", color=COLORS["orange"])
        ax2.tick_params(axis="y", labelcolor=COLORS["orange"])

    filtered_df_both = data_frame.dropna(subset=["体重", "体脂率"])
    if not filtered_df_both.empty:
        fat_mass = (
            filtered_df_both["体脂率"].to_numpy()
            * 0.01
            * filtered_df_both["体重"].to_numpy()
        )
        ax3 = ax1.twinx()
        ax3.spines["right"].set_position(("outward", 60))
        lns3 = ax3.plot(
            filtered_df_both["日期"],
            fat_mass,
            "-",
            label="脂肪质量",
            color=COLORS["red"],
            linewidth=1.8,
            alpha=0.85,
        )
        ax3.set_ylabel("脂肪质量(kg)", color=COLORS["red"])
        ax3.tick_params(axis="y", labelcolor=COLORS["red"])

    lns = lns1 + lns2 + lns3
    labels = [line.get_label() for line in lns]
    ax1.legend(lns, labels, loc="upper left", ncol=3, fontsize=12)
    format_date_axis(ax1, recent_days)
    fig.autofmt_xdate()
    ax1.set_title("体重 / 体脂率 / 脂肪质量趋势", color=COLORS["gray"], pad=16)
    apply_axis_style(ax1)
    ax1.set_axisbelow(True)
    plt.tight_layout()
    save_figure(fig, output_dir, f"weight_bodyfat_{recent_days}d")


def compute_time_allocation_with_warnings(data_frame):
    filtered_df = data_frame.dropna(subset=["睡眠时间", "手机屏幕\n使用时间"]).copy()
    if filtered_df.empty:
        raise ValueError("时间数据为空，无法绘图")

    valid_indices = []
    valid_sleep_hours = []
    valid_screen_hours = []
    skipped_rows = []

    for index, row in filtered_df.iterrows():
        sleep_hours = time_to_hour(row["睡眠时间"], row_index=index, column_name="睡眠时间")
        screen_hours = time_to_hour(
            row["手机屏幕\n使用时间"],
            row_index=index,
            column_name="手机屏幕\n使用时间",
        )

        if sleep_hours is None or screen_hours is None:
            skipped_rows.append(
                {
                    "日期": row.get("日期"),
                    "睡眠时间": row.get("睡眠时间"),
                    "手机屏幕使用时间": row.get("手机屏幕\n使用时间"),
                    "原因": "时间格式无效",
                }
            )
            continue

        remaining_hours = 24 - (sleep_hours + screen_hours)
        if remaining_hours <= 0:
            skipped_rows.append(
                {
                    "日期": row.get("日期"),
                    "睡眠时间": row.get("睡眠时间"),
                    "手机屏幕使用时间": row.get("手机屏幕\n使用时间"),
                    "原因": "睡眠时间+手机屏幕使用时间 > 24小时",
                }
            )
            continue

        valid_indices.append(index)
        valid_sleep_hours.append(sleep_hours)
        valid_screen_hours.append(screen_hours)

    if skipped_rows:
        print("警告：以下行的时间数据无效，已跳过，不参与时间图表统计")
        print(pd.DataFrame(skipped_rows).to_string(index=False))

    if not valid_indices:
        raise ValueError("有效时间数据为空，无法绘图")

    filtered_df = filtered_df.loc[valid_indices].copy()
    valid_sleep_hours = np.array(valid_sleep_hours, dtype=float)
    valid_screen_hours = np.array(valid_screen_hours, dtype=float)
    remaining_hours = 24 - (valid_sleep_hours + valid_screen_hours)

    return filtered_df, valid_sleep_hours, valid_screen_hours, remaining_hours, skipped_rows


def compute_time_allocation(data_frame):
    filtered_df, valid_sleep_hours, valid_screen_hours, remaining_hours, _ = compute_time_allocation_with_warnings(
        data_frame
    )
    return filtered_df, valid_sleep_hours, valid_screen_hours, remaining_hours


def plot_time_allocation_bar(
    nearest_days,
    filtered_df,
    valid_sleep_hours,
    valid_screen_hours,
    remaining_hours,
    is_show=True,
    output_dir=None,
):
    date = filtered_df["日期"].tail(nearest_days)
    average_sleep_time = valid_sleep_hours[-nearest_days:].mean()
    average_screen_time = valid_screen_hours[-nearest_days:].mean()
    average_remaining_time = remaining_hours[-nearest_days:].mean()

    if is_show:
        fig, ax = plt.subplots(figsize=get_figsize("time_bar", nearest_days))
        label = (
            "睡眠时间"
            + f" 平均：{format_hours_label(average_sleep_time)}"
        )
        ax.bar(
            date,
            valid_sleep_hours[-nearest_days:],
            label=label,
            color=COLORS["green"],
            bottom=remaining_hours[-nearest_days:] + valid_screen_hours[-nearest_days:],
        )
        label = (
            "手机屏幕使用时间"
            + f" 平均：{format_hours_label(average_screen_time)}"
        )
        ax.bar(
            date,
            valid_screen_hours[-nearest_days:],
            label=label,
            color=COLORS["orange"],
            bottom=remaining_hours[-nearest_days:],
        )
        label = (
            "剩余时间"
            + f" 平均：{format_hours_label(average_remaining_time)}"
        )
        ax.bar(
            date,
            remaining_hours[-nearest_days:],
            label=label,
            color=COLORS["lightblue"],
            bottom=0,
        )
        ax.set_xlabel("日期")
        ax.set_ylabel("Hours")
        format_date_axis(ax, nearest_days)
        fig.autofmt_xdate()
        ax.set_ylim(0, 24)
        ax.set_title(f"近{nearest_days}个有效数据日时间分配", color=COLORS["gray"], pad=16)
        ax.legend(loc="upper center", ncol=3, fontsize=12)
        apply_axis_style(ax, grid_axis="y")
        ax.set_axisbelow(True)
        suffix = f"{nearest_days}d"
        # If nearest_days covers the entire dataset (or more), treat as "all" and cleanup old dynamic files
        if nearest_days >= len(filtered_df):
            suffix = "all"
            if output_dir:
                try:
                    pattern = os.path.join(output_dir, "time_allocation_bar_*d.png")
                    for f in glob.glob(pattern):
                        # Keep fixed duration plots like 30d
                        if f.endswith("time_allocation_bar_30d.png"):
                            continue
                        # Delete dynamic day counts (e.g. 683d, 684d etc)
                        if re.search(r"time_allocation_bar_\d+d\.png", os.path.basename(f)):
                            try:
                                os.remove(f)
                                print(f"Cleaned up redundant plot: {os.path.basename(f)}")
                            except OSError:
                                pass
                except Exception as e:
                    print(f"Cleanup warning: {e}")

        save_figure(fig, output_dir, f"time_allocation_bar_{suffix}")

    return average_sleep_time, average_screen_time, average_remaining_time


def plot_time_trends(
    filtered_df,
    valid_sleep_hours,
    valid_screen_hours,
    remaining_hours,
    nearest_days=120,
    output_dir=None,
):
    filtered_df_1 = filtered_df
    filtered_df_2 = filtered_df
    filtered_df_3 = filtered_df

    if filtered_df_1.empty or filtered_df_2.empty or filtered_df_3.empty:
        raise ValueError("用于趋势图的数据为空")

    nearest_days = min(nearest_days, len(filtered_df_1), len(filtered_df_2), len(filtered_df_3))

    valid_1 = valid_sleep_hours
    valid_2 = valid_screen_hours

    y1 = np.zeros(len(filtered_df_1))
    y2 = np.zeros(len(filtered_df_2))
    y3 = np.zeros(len(filtered_df_3))

    for i in range(len(filtered_df_1)):
        y1[i] = valid_1[i:].mean()
    for i in range(len(filtered_df_2)):
        y2[i] = valid_2[i:].mean()
    for i in range(len(filtered_df_3)):
        y3[i] = remaining_hours[i:].mean()

    fig1, ax1 = plt.subplots(figsize=get_figsize("time_trend", nearest_days))
    ax1.plot(
        filtered_df_2["日期"],
        valid_2,
        "-",
        label="手机屏幕使用时间",
        color=COLORS["orange"],
        alpha=0.6,
        linewidth=1.4,
    )
    ax1.plot(
        filtered_df_3["日期"],
        remaining_hours,
        "-",
        label="剩余时间",
        color=COLORS["lightblue"],
        alpha=0.6,
        linewidth=1.4,
    )
    ax1.plot(
        filtered_df_2["日期"],
        y2,
        "--",
        label="平均手机屏幕使用时间",
        color=COLORS["orange"],
        linewidth=2.2,
    )
    ax1.plot(
        filtered_df_3["日期"],
        y3,
        "--",
        label="平均剩余时间",
        color=COLORS["lightblue"],
        linewidth=2.2,
    )
    format_date_axis(ax1, nearest_days)
    fig1.autofmt_xdate()
    ax1.set_xlabel("日期")
    ax1.set_ylabel("Hours")
    apply_axis_style(ax1)
    ax1.set_xlim(
        min(filtered_df_1["日期"].iloc[-nearest_days], filtered_df_2["日期"].iloc[-nearest_days]),
        max(filtered_df_1["日期"].max(), filtered_df_2["日期"].max()),
    )
    ax1.set_ylim(1, 14)
    ax1.set_title("手机屏幕与剩余时间趋势（含均线）", color=COLORS["gray"], pad=16)
    ax1.legend(loc="upper left", ncol=2, fontsize=12)
    save_figure(fig1, output_dir, f"time_trend_screen_remaining_{nearest_days}d")

    fig2, ax2 = plt.subplots(figsize=get_figsize("time_trend", nearest_days))
    ax2.plot(filtered_df_1["日期"], y1, "-", label="平均睡眠时间", color=COLORS["green"])
    ax2.plot(
        filtered_df_1["日期"],
        y1 * 0.0 + 8.0,
        "--",
        linewidth=2.0,
        label="目标睡眠时间8小时",
        color=COLORS["green"],
        alpha=0.7,
    )
    ax2.plot(filtered_df_2["日期"], y2, "-", label="平均手机屏幕使用时间", color=COLORS["orange"])
    ax2.plot(
        filtered_df_2["日期"],
        y2 * 0.0 + 4.0,
        "--",
        linewidth=2.0,
        label="目标手机屏幕使用时间4小时",
        color=COLORS["orange"],
        alpha=0.7,
    )
    ax2.plot(filtered_df_3["日期"], y3, "-", label="平均剩余时间", color=COLORS["lightblue"])
    ax2.plot(
        filtered_df_3["日期"],
        y3 * 0.0 + 12.0,
        "--",
        linewidth=2.0,
        label="目标剩余时间12小时",
        color=COLORS["lightblue"],
        alpha=0.7,
    )
    format_date_axis(ax2, nearest_days)
    fig2.autofmt_xdate()
    ax2.set_xlabel("日期")
    ax2.set_ylabel("Hours")
    apply_axis_style(ax2)
    ax2.set_xlim(
        min(filtered_df_1["日期"].iloc[-nearest_days], filtered_df_2["日期"].iloc[-nearest_days]),
        max(filtered_df_1["日期"].max(), filtered_df_2["日期"].max()),
    )
    ax2.set_ylim(1, 14)
    ax2.set_title("睡眠 / 手机屏幕 / 剩余时间均线", color=COLORS["gray"], pad=16)
    ax2.legend(loc="upper left", ncol=2, fontsize=12)
    save_figure(fig2, output_dir, f"time_trend_averages_{nearest_days}d")

    fig3, ax3 = plt.subplots(figsize=get_figsize("time_trend", nearest_days))
    ax3.plot(filtered_df_1["日期"], (y1 - 8.0), "-", label="平均睡眠时间 -8h", color=COLORS["green"])
    ax3.plot(
        filtered_df_2["日期"],
        (y2 - 4.0),
        "-",
        label="平均手机屏幕使用时间 -4h",
        color=COLORS["orange"],
    )
    ax3.plot(
        filtered_df_3["日期"],
        (y3 - 12.0),
        "-",
        label="平均剩余时间 -12h",
        color=COLORS["lightblue"],
    )
    format_date_axis(ax3, nearest_days)
    fig3.autofmt_xdate()
    ax3.set_xlabel("日期")
    ax3.set_ylabel("Hours")
    apply_axis_style(ax3)
    ax3.set_xlim(
        min(filtered_df_1["日期"].iloc[-nearest_days], filtered_df_2["日期"].iloc[-nearest_days]),
        max(filtered_df_1["日期"].max(), filtered_df_2["日期"].max()),
    )
    ax3.set_title("距离目标的差距（越接近0越好）", color=COLORS["gray"], pad=16)
    ax3.legend(loc="upper left", ncol=2, fontsize=12)
    save_figure(fig3, output_dir, f"time_trend_delta_{nearest_days}d")

    return y1, y2, y3, nearest_days


def compute_score(average, compare_mode="bigger_than", goal=100, max=100, min=0):
    if compare_mode == "bigger_than":
        max = goal
        if average >= max:
            score = 1
        elif average <= min:
            score = 0
        else:
            score = (average - min) / (max - min)
    elif compare_mode == "smaller_than":
        min = goal
        if average <= min:
            score = 1
        elif average >= max:
            score = 0
        else:
            score = 1 - (average - min) / (max - min)
    return 100 * score


def plot_radar_goal_achievement(y1, y2, y3, nearest_days, data_frame, output_dir=None):
    labels = ["睡眠时间", "手机屏幕使用时间", "剩余时间", "体重", "体脂率"]
    num_vars = len(labels)
    values = [0] * num_vars

    values[0] = compute_score(y1[-nearest_days], compare_mode="bigger_than", goal=8, min=5)
    values[1] = compute_score(y2[-nearest_days], compare_mode="smaller_than", goal=4, max=24)
    values[2] = compute_score(y3[-nearest_days], compare_mode="bigger_than", goal=12, min=4)

    average_weight = np.average(data_frame["体重"].dropna().to_numpy())
    average_body_fat_rate = np.average(data_frame["体脂率"].dropna().to_numpy())
    values[3] = compute_score(average_weight, compare_mode="smaller_than", goal=65, max=75)
    values[4] = compute_score(average_body_fat_rate, compare_mode="smaller_than", goal=15, max=30)

    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()
    values += values[:1]
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=get_figsize("radar"), subplot_kw=dict(polar=True))
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.fill(angles, values, color=COLORS["green"], alpha=0.25)
    ax.plot(angles, values, color=COLORS["green"], linewidth=2.2, marker="o")

    ax.set_facecolor("#f9f9f9")
    ax.spines["polar"].set_visible(False)

    ax.set_yticks([20, 40, 60, 80, 100])
    ax.set_yticklabels(["20%", "40%", "60%", "80%", "100%"], color=COLORS["gray"], fontsize=9)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=11, color=COLORS["gray"])
    ax.grid(color="#b0b0b0", linestyle="--", linewidth=0.6, alpha=0.6)

    for angle, value in zip(angles, values):
        ax.text(angle, value + 4, f"{value:.0f}%", ha="center", fontsize=9, color=COLORS["gray"])

    ax.set_title(f"近 {nearest_days} 天目标达成率", color=COLORS["gray"], pad=24)
    save_figure(fig, output_dir, f"radar_goal_{nearest_days}d")


def plot_hhh_stats(data_frame, output_dir=None):
    if "HHH" not in data_frame.columns:
        print("数据中未找到 HHH 列。当前可用列为:", list(data_frame.columns))
        return

    def calculate_intervals(date_series):
        dates = pd.to_datetime(date_series).sort_values()
        return dates.diff().dt.days.dropna().tolist()

    def _parse_hhh_value(val):
        """智能解析 HHH 列的值，处理数字和字符串混合情况。
        实际数据中发现类似 '19.50 -1' 这种空格分隔多值的情况，取最后一个数字。
        """
        if isinstance(val, (int, float)):
            return val
        if not isinstance(val, str):
            return None
        # 先尝试直接转数字
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
        # 空格分隔的多个值，取最后一个数字（如 '19.50 -1' → -1）
        parts = val.strip().split()
        for part in reversed(parts):
            try:
                return float(part)
            except (ValueError, TypeError):
                continue
        return None

    hhh_data = data_frame[["日期", "HHH"]].dropna()
    hhh_data = hhh_data.copy()
    hhh_data["HHH"] = hhh_data["HHH"].apply(_parse_hhh_value)
    hhh_data = hhh_data.dropna(subset=["HHH"])
    sexual_intercourse = hhh_data[hhh_data["HHH"] > 0]
    masturbation = hhh_data[hhh_data["HHH"] < 0]

    fig, ax = plt.subplots(figsize=get_figsize("hhh_scatter"))

    if not sexual_intercourse.empty:
        ax.scatter(
            sexual_intercourse["日期"],
            sexual_intercourse["HHH"],
            color=COLORS["blue"],
            label="性生活",
            s=50,
            alpha=0.75,
        )

    if not masturbation.empty:
        ax.scatter(
            masturbation["日期"],
            abs(masturbation["HHH"]),
            color=COLORS["red"],
            label="自慰",
            s=50,
            alpha=0.75,
        )

    format_date_axis(ax, 365)
    fig.autofmt_xdate()

    ax.set_xlabel("日期")
    ax.set_ylabel("频次")
    ax.set_title("性生活 vs 自慰 频率变化趋势", color=COLORS["gray"], pad=16)
    ax.legend(loc="upper left", ncol=2, fontsize=12)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    apply_axis_style(ax)

    plt.tight_layout()
    save_figure(fig, output_dir, "hhh_frequency")

    if not sexual_intercourse.empty:
        intercourse_intervals = calculate_intervals(sexual_intercourse["日期"])
        avg_intercourse_interval = (
            sum(intercourse_intervals) / len(intercourse_intervals)
            if intercourse_intervals
            else None
        )
        print(f"性生活总次数: {len(sexual_intercourse)}")
        print(f"平均每隔 {avg_intercourse_interval:.1f} 天性生活一次")
    else:
        intercourse_intervals = []

    if not masturbation.empty:
        masturbation_intervals = calculate_intervals(masturbation["日期"])
        avg_masturbation_interval = (
            sum(masturbation_intervals) / len(masturbation_intervals)
            if masturbation_intervals
            else None
        )
        print(f"自慰总次数: {len(masturbation)}")
        print(f"平均每隔 {avg_masturbation_interval:.1f} 天自慰一次")
    else:
        masturbation_intervals = []

    fig, ax = plt.subplots(figsize=get_figsize("hhh_interval"))

    if intercourse_intervals:
        ax.plot(intercourse_intervals, marker="o", label="性生活间隔（天）", color=COLORS["blue"])

    if masturbation_intervals:
        ax.plot(masturbation_intervals, marker="x", label="自慰间隔（天）", color=COLORS["red"])

    ax.set_xlabel("第 N 次行为")
    ax.set_ylabel("距离上一次的天数")
    ax.set_title("性生活 / 自慰 间隔天数趋势", color=COLORS["gray"], pad=12)
    ax.legend(loc="upper left", ncol=2, fontsize=12)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    apply_axis_style(ax)

    plt.tight_layout()
    save_figure(fig, output_dir, "hhh_interval_trend")


def load_balance_sheet(path=None):
    if path is None:
        path = resolve_data_path("Balance Sheet.xlsx")
    return load_excel_safely(path)


def plot_balance_sheet(data_frame_balance, output_dir=None):
    date = data_frame_balance["日期"]
    day_average_expenditure = data_frame_balance["日均支出"]

    fig, ax1 = plt.subplots(figsize=get_figsize("balance"))
    balance = data_frame_balance["现金及现金等价物+股票"].to_numpy()

    ax1.plot(
        date,
        balance,
        "-",
        label="现金及现金等价物+股票",
        color=COLORS["blue"],
        linewidth=2.0,
        markersize=8,
    )
    ax1.set_xlabel("日期")
    ax1.set_ylabel("现金及现金等价物+股票", color=COLORS["blue"])
    ax1.tick_params(axis="y", labelcolor=COLORS["blue"])
    apply_axis_style(ax1)
    ax1.set_title("资产与支出趋势", color=COLORS["gray"], pad=16)

    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate(rotation=45)

    ax2 = ax1.twinx()
    ax2.plot(
        date,
        day_average_expenditure,
        "-",
        label="日均支出",
        color=COLORS["orange"],
        linewidth=2.0,
        markersize=6,
    )
    ax2.set_ylabel("日均支出", color=COLORS["orange"])
    ax2.tick_params(axis="y", labelcolor=COLORS["orange"])

    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc="upper left", ncol=2, fontsize=12)

    plt.tight_layout()
    save_figure(fig, output_dir, "balance_sheet")


def _parse_distance_km(text):
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|公里|千米)", text, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _parse_time_minutes(text):
    match = re.search(
        r"(?:用时|时间|耗时|时长)\s*(\d+)\s*(?:分|分钟)(?:\s*(\d+))?",
        text,
    )
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2)) if match.group(2) else 0
        return minutes + seconds / 60.0
    return None


def _parse_pace_minutes(text):
    match = re.search(r"配速\s*(\d+)\s*:\s*(\d+)", text)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        return minutes + seconds / 60.0
    match = re.search(r"配速\s*(\d+)\s*(?:分|分钟)\s*(\d+)?", text)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2)) if match.group(2) else 0
        return minutes + seconds / 60.0
    return None


def _parse_int_field(text, label):
    match = re.search(rf"{label}\s*(\d+)", text)
    if match:
        return int(match.group(1))
    return None


def _parse_float_field(text, label):
    match = re.search(rf"{label}\s*(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    return None


def _format_minutes_to_mmss(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    total_seconds = int(round(value * 60))
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _looks_like_running_text(text):
    if not isinstance(text, str):
        return False

    lowered = text.lower()
    running_keywords = ("跑步", "慢跑", "快跑", "夜跑", "晨跑", "跑了", "竞速", "配速")
    running_metric_keywords = ("步频", "步幅")
    walking_keywords = ("走了", "走路", "散步", "步行", "徒步", "快走", "暴走", "绕湖走")

    has_running_keyword = any(keyword in text for keyword in running_keywords)
    has_running_metric_keyword = any(keyword in text for keyword in running_metric_keywords)
    has_walking_keyword = any(keyword in text for keyword in walking_keywords)
    has_distance_keyword = "公里" in text or "km" in lowered
    has_time_keyword = "用时" in text or "分钟" in text or "分" in text

    if has_running_keyword or has_running_metric_keyword:
        return True

    if has_walking_keyword:
        return False

    return has_distance_keyword and has_time_keyword


def _parse_running_text(text):
    if not isinstance(text, str):
        return None

    distance_km = _parse_distance_km(text)
    time_min = _parse_time_minutes(text)
    pace_min = _parse_pace_minutes(text)
    heart_rate = _parse_int_field(text, "心率")
    cadence = _parse_int_field(text, "步频")
    stride = _parse_float_field(text, "步幅")

    if not _looks_like_running_text(text):
        return None

    if distance_km is None and time_min is not None and pace_min:
        distance_km = time_min / pace_min
    if pace_min is None and time_min is not None and distance_km:
        pace_min = time_min / distance_km
    if time_min is None and pace_min is not None and distance_km:
        time_min = pace_min * distance_km

    pace_over_hr = None
    if pace_min is not None and heart_rate:
        pace_over_hr = pace_min / heart_rate

    return {
        "距离_km": distance_km,
        "用时_min": time_min,
        "配速_min_per_km": pace_min,
        "心率": heart_rate,
        "步频": cadence,
        "步幅": stride,
        "配速除以心率": pace_over_hr,
        "运动文本": text,
    }


def compute_running_metrics(
    data_frame,
    source_col="运动",
    date_col="日期",
    output_dir=None,
):
    if source_col not in data_frame.columns:
        print(f"数据中未找到 {source_col} 列。当前可用列为:", list(data_frame.columns))
        return pd.DataFrame()

    records = []
    for _, row in data_frame[[date_col, source_col]].dropna(subset=[source_col]).iterrows():
        metrics = _parse_running_text(str(row[source_col]))
        if metrics is None:
            continue
        metrics[date_col] = row[date_col]
        records.append(metrics)

    if not records:
        print("未找到跑步记录")
        return pd.DataFrame()

    result = pd.DataFrame(records)
    result.sort_values(date_col, inplace=True)
    result["配速_mmss"] = result["配速_min_per_km"].apply(_format_minutes_to_mmss)
    result["用时_mmss"] = result["用时_min"].apply(_format_minutes_to_mmss)
    result["distance_km"] = result["距离_km"]
    result["duration_min"] = result["用时_min"]
    result["duration_mmss"] = result["用时_mmss"]
    result["pace_min_per_km"] = result["配速_min_per_km"]
    result["pace_mmss"] = result["配速_mmss"]
    result["heart_rate_bpm"] = result["心率"]
    cadence_raw = pd.to_numeric(result["步频"], errors="coerce")
    stride_raw = pd.to_numeric(result["步幅"], errors="coerce")
    result["speed_m_per_min"] = np.where(
        result["duration_min"] > 0,
        result["distance_km"] * 1000.0 / result["duration_min"],
        np.nan,
    )
    normalized_stride_m = np.where(stride_raw.abs() > 10, stride_raw / 100.0, stride_raw)
    inferred_cadence_spm = np.where(
        (normalized_stride_m > 0) & np.isfinite(result["speed_m_per_min"]),
        result["speed_m_per_min"] / normalized_stride_m,
        np.nan,
    )
    result["cadence_spm"] = np.where(pd.notna(cadence_raw), cadence_raw, inferred_cadence_spm)
    inferred_stride_m = np.where(
        (result["cadence_spm"] > 0) & np.isfinite(result["speed_m_per_min"]),
        result["speed_m_per_min"] / result["cadence_spm"],
        np.nan,
    )
    result["stride_m"] = np.where(pd.notna(normalized_stride_m), normalized_stride_m, inferred_stride_m)
    result["speed_km_per_h"] = result["speed_m_per_min"] * 0.06
    result["HRC_m_per_beat"] = np.where(
        (result["heart_rate_bpm"] > 0) & np.isfinite(result["speed_m_per_min"]),
        result["speed_m_per_min"] / result["heart_rate_bpm"],
        np.nan,
    )
    invalid_rows = []
    for _, row in result.iterrows():
        missing_by_chart = {}

        running_missing = []
        if pd.isna(row.get("pace_min_per_km")):
            running_missing.append("配速")
        if pd.isna(row.get("heart_rate_bpm")):
            running_missing.append("心率")
        if pd.isna(row.get("distance_km")):
            running_missing.append("距离")
        if running_missing:
            missing_by_chart["running"] = running_missing

        running_form_missing = []
        if pd.isna(row.get("duration_min")):
            running_form_missing.append("用时")
        if pd.isna(row.get("cadence_spm")):
            running_form_missing.append("步频")
        if pd.isna(row.get("stride_m")):
            running_form_missing.append("步幅")
        if running_form_missing:
            missing_by_chart["running-form"] = running_form_missing

        running_hrc_missing = []
        if pd.isna(row.get("distance_km")):
            running_hrc_missing.append("距离")
        if pd.isna(row.get("duration_min")):
            running_hrc_missing.append("用时/配速")
        if pd.isna(row.get("heart_rate_bpm")):
            running_hrc_missing.append("心率")
        if pd.isna(row.get("HRC_m_per_beat")):
            running_hrc_missing.append("HRC")
        if running_hrc_missing:
            deduped_missing = list(dict.fromkeys(running_hrc_missing))
            missing_by_chart["running-hrc"] = deduped_missing

        if not missing_by_chart:
            continue

        invalid_rows.append(
            {
                "日期": row.get(date_col),
                "原文": row.get("运动文本"),
                "missing_by_chart": missing_by_chart,
            }
        )
    result.attrs["invalid_rows"] = invalid_rows

    if output_dir is not None:
        output_path = Path(output_dir) / "running_metrics.csv"
        result.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"跑步指标已保存: {output_path}")

    return result


def plot_running_pace(data_frame, output_dir=None):
    running_df = compute_running_metrics(data_frame)
    if running_df.empty or "配速_min_per_km" not in running_df:
        print("未找到可绘制的跑步配速数据")
        return

    running_df = running_df.dropna(subset=["配速_min_per_km"])
    if running_df.empty:
        print("未找到可绘制的跑步配速数据")
        return

    date_col = "日期" if "日期" in running_df.columns else running_df.columns[0]
    days = (running_df[date_col].max() - running_df[date_col].min()).days + 1

    fig, ax = plt.subplots(figsize=get_figsize("running"))
    ax.plot(
        running_df[date_col],
        running_df["配速_min_per_km"],
        "-",
        color=COLORS["purple"],
        label="配速（min/km）",
        alpha=0.9,
    )

    def pace_formatter(value, _pos):
        if value is None or np.isnan(value):
            return ""
        minutes = int(value)
        seconds = int(round((value - minutes) * 60))
        return f"{minutes}:{seconds:02d}"

    ax.yaxis.set_major_formatter(FuncFormatter(pace_formatter))
    format_date_axis(ax, max(days, 1))
    fig.autofmt_xdate()
    ax.set_xlabel("日期")
    ax.set_ylabel("配速 (min/km)")
    ax.set_title("跑步配速趋势", color=COLORS["gray"], pad=16)
    ax.legend(loc="upper left", fontsize=12)
    apply_axis_style(ax)
    save_figure(fig, output_dir, "running_pace")


def generate_all_plots(output_dir=None, is_dark_mode=False):
    configure_matplotlib(is_dark_mode)

    output_dir = resolve_output_dir()
    data_frame = load_time_data()

    plot_weight_and_body_fat_rate(data_frame, recent_days=365 * 3, output_dir=output_dir)
    plot_weight_and_body_fat_rate(data_frame, recent_days=300 * 1, output_dir=output_dir)
    plot_weight_and_body_fat_rate(data_frame, recent_days=100, output_dir=output_dir)
    plot_weight_and_body_fat_rate(data_frame, recent_days=30, output_dir=output_dir)
    plot_weight_and_body_fat_rate(data_frame, recent_days=7, output_dir=output_dir)

    filtered_df, valid_sleep_hours, valid_screen_hours, remaining_hours = compute_time_allocation(
        data_frame
    )
    plot_time_allocation_bar(
        len(filtered_df),
        filtered_df,
        valid_sleep_hours,
        valid_screen_hours,
        remaining_hours,
        output_dir=output_dir,
    )
    plot_time_allocation_bar(
        30,
        filtered_df,
        valid_sleep_hours,
        valid_screen_hours,
        remaining_hours,
        output_dir=output_dir,
    )

    y1, y2, y3, nearest_days = plot_time_trends(
        filtered_df,
        valid_sleep_hours,
        valid_screen_hours,
        remaining_hours,
        nearest_days=120,
        output_dir=output_dir,
    )
    plot_radar_goal_achievement(y1, y2, y3, nearest_days, data_frame, output_dir=output_dir)

    plot_hhh_stats(data_frame, output_dir=output_dir)

    data_frame_balance = load_balance_sheet()
    plot_balance_sheet(data_frame_balance, output_dir=output_dir)

    compute_running_metrics(data_frame, output_dir=output_dir)
    plot_running_pace(data_frame, output_dir=output_dir)
    merge_plot_images(output_dir, is_dark_mode=is_dark_mode)


if __name__ == "__main__":
    import sys
    is_dark = "--dark" in sys.argv
    generate_all_plots(is_dark_mode=is_dark)
