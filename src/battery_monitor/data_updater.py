from ctypes.wintypes import ULONG
from ctypes import windll, POINTER, c_ulong, byref, Structure
import psutil
from datetime import datetime
import winrt.windows.devices.power as power
from datetime import datetime
import psutil
import ctypes
import tkinter as tk
from ctypes import wintypes
from threading import Thread
import time
import wmi
# 全局变量
time_data = []
charge_percent_data = []
power_data = []
start_time_global = None

# 获取充电功率


def get_battery_rate():
    # 创建 WMI 对象，用于查询 Windows 管理信息（WMI）
    c = wmi.WMI()  # 获取所有可用的电池信息
    t = wmi.WMI(moniker="//./root/wmi")  # 用于查询特定的 WMI 命名空间

    # 初始化用于存储电池信息的变量
    watthours = 0  # 剩余电量，单位：瓦时（Wh）
    watts = 0  # 放电功率，单位：瓦特（W）
    charge_watts = 0  # 充电功率，单位：瓦特（W）

    # 查询电池的状态，确保电池电压大于 0
    batts = t.ExecQuery('Select * from BatteryStatus where Voltage > 0')

    # 获取更多的电池信息，例如关于“Portable Battery”的详细信息
    batts1 = c.CIM_Battery(Caption='Portable Battery')

    # 可以根据不同品牌的需要调整查询，以下行被注释掉：
    # batts = t.ExecQuery('Select * from BatteryStatus ')

    # 遍历查询结果中的每个电池信息
    for i, b in enumerate(batts):
        # 获取放电功率，单位为瓦特（W），放电速率以毫安为单位，因此要除以1000转换为瓦特
        watts = b.DischargeRate / 1000.0
        # 获取剩余电量，单位：瓦时（Wh），需要从毫瓦时（mWh）转换为瓦时
        watthours = b.RemainingCapacity / 1000

        # 如果电池正在充电，计算充电功率
        if b.Charging == 1:  # 判断是否正在充电
            # 充电功率的计算（假设使用同样的单位转换规则）
            charge_watts = b.ChargeRate / 1000.0  # 充电速率通常以毫安为单位，转换为瓦特

    # 如果放电功率不为零，计算电池剩余使用时间
    hoursleft = 0
    if watts != 0:  # 判断电池是否正在放电
        hoursleft = (watthours / watts)  # 计算剩余时间，单位：小时

    # 输出电池的信息：包括功率、剩余电量和剩余使用时间
    txtlong = "Discharge Watts: {0:2.1f} Discharge Watthours: {1:2.1f} Discharge Hours left: {2:2.1f} Charge Watts: {3:2.1f}"
    txtlong = "放电功率: {0:2.1f} W 剩余电量: {1:2.1f} Wh 剩余使用时间: {2:2.1f} Hours 充电功率: {3:2.1f} W"
    # 格式化字符串输出功率（放电功率）、剩余电量和剩余使用时间，以及充电功率
    print(txtlong.format(watts, watthours, hoursleft, charge_watts))

    # 返回充电功率（正数） 放电攻略（负数）
    temp = charge_watts - watts
    return temp


# 更新电池数据
def update_data():
    global start_time_global, time_data, charge_percent_data, power_data
    while True:
        try:
            battery = psutil.sensors_battery()
            if battery is None:
                print("未检测到电池设备，请确认设备是否支持电池监控。")
                return

            charge_percent = battery.percent
            rate_w = get_battery_rate()

            # 获取当前时间戳
            current_time = datetime.now()

            # 设置起始时间
            if start_time_global is None:
                start_time_global = current_time

            # 计算相对时间（秒）
            elapsed_time = (current_time - start_time_global).total_seconds()

            # 添加数据
            time_data.append(elapsed_time)
            charge_percent_data.append(charge_percent)
            power_data.append(rate_w if rate_w else 0)

        except Exception as e:
            print(f"错误: {e}")

        # 功率变化频率为0.5s一次
        time.sleep(0.5)
