import os


def find_code_files(directory, extensions):
    """
    在指定目录中查找所有符合扩展名的代码文件。
    :param directory: 要扫描的目录
    :param extensions: 代码文件的扩展名列表，例如 ['.py', '.cpp', '.cu']
    :return: 代码文件的路径列表
    """

    code_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if any(file.endswith(ext) for ext in extensions):
                code_files.append(os.path.join(root, file))
    return code_files


if __name__ == "__main__":
    # 获取当前脚本文件所在的目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    directory = "../../tests/code_folder"  # 这里替换成你的目标目录
    # 将相对路径转换为绝对路径
    abs_directory = os.path.join(script_dir, directory)

    extensions = [".py", ".cpp", ".cu"]  # 这里根据你的需求调整
    files = find_code_files(abs_directory, extensions)
    print("在目录", directory, "找到的代码文件：", files)
