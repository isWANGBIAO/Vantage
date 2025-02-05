import os
import shutil


def backup_directory(directory):
    """
    备份整个目录到 backup 文件夹。

    :param directory: 需要备份的目录
    """
    # 使用os.path.abspath确保目录路径是绝对路径
    directory = os.path.abspath(directory)

    # 使用os.path.dirname获取目录的父目录，然后在其下创建backup文件夹
    backup_dir = os.path.join(os.path.dirname(directory), "backup")

    # 检查备份目录是否存在，如果不存在则创建备份
    if not os.path.exists(backup_dir):
        # 使用shutil.copytree复制整个目录树到备份目录
        shutil.copytree(directory, backup_dir)
        print(f"已成功备份目录: {backup_dir}")
    else:
        print(f"备份目录已存在: {backup_dir}")


# 示例调用
# backup_directory("path/to/your/directory")
