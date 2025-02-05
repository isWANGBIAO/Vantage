'''
可以写一个简单的 Python 或 Bash 脚本，逐行读取 requirements.txt，即使某个包失败，仍继续安装其他包。
'''
import os

# 打开requirements.txt文件，使用with语句确保文件在使用后正确关闭
with open('requirements.txt', 'r') as file:
    # 遍历文件的每一行
    for line in file:
        # 去除行两端的空白字符
        package = line.strip()
        # 检查行是否不为空且不是注释
        if package and not package.startswith('#'):
            # 打印正在安装的包名
            print(f"Installing {package}...")
            # 执行系统命令安装包，并获取退出码
            exit_code = os.system(f'pip install {package}')
            # 如果退出码不为0，说明安装失败
            if exit_code != 0:
                # 打印失败信息，并跳过当前包的安装
                print(f"Failed to install {package}, skipping...\n")
