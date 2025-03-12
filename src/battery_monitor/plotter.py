import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

# 绘图函数


def update_plot(i, ax1, ax2, ax3, line1, line2, line3, time_data, charge_percent_data, power_data):
    if not time_data or not charge_percent_data or not power_data:
        return

    # 更新曲线数据
    line1.set_data(time_data, charge_percent_data)  # 电量百分比-时间
    line2.set_data(charge_percent_data, power_data)  # 充电功率-电量百分比
    line3.set_data(time_data, power_data)  # 充电功率-时间

    # 更新坐标轴范围
    ax1.set_xlim(0, max(time_data))
    ax1.set_ylim(0, 100)
    ax2.set_xlim(0, 100)
    ax2.set_ylim(min(power_data), max(power_data))
    ax3.set_xlim(0, max(time_data))
    ax3.set_ylim(min(power_data), max(power_data))
    ax1.set_xlabel("时间(s)")
    ax3.set_xlabel("时间(s)")

    return line1, line2, line3

# 初始化绘图


def init_plot():
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 8))
    fig.suptitle("电池充电数据实时曲线", fontsize=16)

    # 配置子图
    ax1.set_title("充电百分比-时间曲线")
    ax1.set_ylabel("充电百分比 (%)")

    ax2.set_title("充电功率-充电百分比曲线")
    ax2.set_xlabel("充电百分比 (%)")
    ax2.set_ylabel("充电功率 (W)")

    ax3.set_title("充电功率-时间曲线")
    ax3.set_ylabel("充电功率 (W)")

    # 创建空曲线
    line1, = ax1.plot([], [], linewidth=1.0, label="充电百分比", color="blue")
    line2, = ax2.plot([], [], linewidth=1.0, label="功率 vs 电量", color="green")
    line3, = ax3.plot([], [], linewidth=1.0, label="功率 vs 时间", color="red")

    ax1.legend()
    ax2.legend()
    ax3.legend()

    ax1.grid()
    ax2.grid()
    ax3.grid()

    return fig, ax1, ax2, ax3, line1, line2, line3
