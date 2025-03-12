import threading
from data_updater import update_data, time_data, charge_percent_data, power_data
from plotter import init_plot, update_plot
from matplotlib.animation import FuncAnimation
import matplotlib.pyplot as plt
from matplotlib import rcParams
import subprocess
import psutil
import time
import ctypes
from ctypes import wintypes
# 设置中文字体
rcParams['font.sans-serif'] = ['SimSun']
rcParams['axes.unicode_minus'] = False


def main():

    # 启动数据更新线程
    data_thread = threading.Thread(target=update_data, daemon=True)
    data_thread.start()

    # 初始化绘图
    fig, ax1, ax2, ax3, line1, line2, line3 = init_plot()

    # 启动动画
    ani = FuncAnimation(
        fig,
        update_plot,
        fargs=(ax1, ax2, ax3, line1, line2, line3, time_data, charge_percent_data, power_data),
        interval=1000,
        blit=False
    )

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    # TODO: 加入写入日志功能
    # TODO: 加入异常处理
    # TODO: 加入电池参数
    # TODO: 计算大功耗软件
    # TODO: 在右下角托盘显示
    main()
