from .file_scanner import find_code_files
from .code_modifier import modify_code_with_ai
from .code_read import read_code
from .code_write import write_code
from .code_runner import run_code
from .error_handler import analyze_error_with_ai
from .code_adder import add_function_code_with_ai
from .backup_folder import backup_directory
import time


def process_files(directory, extensions, language, max_attempts=5, client=None, golbal_model=None):
    """
    扫描并处理指定目录下的代码文件，直到成功运行或达到最大尝试次数。
    """
    # 找到main.py文件，如果没有则根据指令自动生成代码文件

    # 备份整个项目文件夹

    # 根据main运行整个项目

    # 根据返回的错误信息，打开对应的文件，调用AI进行错误分析并修改代码

    # 再次运行代码，不成功则重复上述步骤

    # 备份整个项目文件夹

    # 从main开始，对每个文件进行处理
    # 读取 -> 修改1次 -> 保存
    code_files = find_code_files(directory, extensions)
    print(f"找到 {len(code_files)} 个 {language} 文件。")

    # 先备份dircetory下所有文件到backup目录，再对每个文件进行处理
    # 先备份整个目录
    backup_directory(directory)
    # 再对每个文件进行处理
    for file_path in code_files:
        print(f"\n处理文件: {file_path}")

        # 读取 -> 修改1次 -> 保存
        original_code = read_code(file_path)
        modified_code = original_code
        for i in range(1):
            modified_code = modify_code_with_ai(modified_code, language, client, golbal_model)
        write_code(file_path, modified_code)

        # # 增加功能并且运行代码
        # while True:
        #     modified_code = add_function_code_with_ai(modified_code, language, client, golbal_model)
        #     write_code(file_path, modified_code)
        #     stdout, stderr = run_code(file_path, language)
        #     if not stderr:
        #         print(f"文件 {file_path} 运行成功！\n输出:\n{stdout}")
        #         break  # 运行成功，退出循环
        #     else:
        #         print(f"运行失败，错误信息:\n{stderr}")
        #         print("调用AI进行错误分析并修改代码...")
        #         modified_code = analyze_error_with_ai(modified_code, stderr, language, client, golbal_model)
        #         write_code(file_path, modified_code)
        #         time.sleep(1)  # 避免API请求过于频繁
        # 运行代码
        attempt = 1
        while attempt <= max_attempts:
            print(f"第 {attempt} 次尝试运行 {file_path}...")
            stdout, stderr = run_code(file_path, language)

            if not stderr:
                print(f"文件 {file_path} 运行成功！\n输出:\n{stdout}")
                break  # 运行成功，退出循环
            else:
                print(f"运行失败，错误信息:\n{stderr}")
                print("调用AI进行错误分析并修改代码...")
                modified_code = analyze_error_with_ai(modified_code, stderr, language, client, golbal_model)
                write_code(file_path, modified_code)
                attempt += 1
                time.sleep(1)  # 避免API请求过于频繁

        if attempt > max_attempts:
            print(f"文件 {file_path} 经过 {max_attempts} 次尝试仍未成功运行，已跳过。")
