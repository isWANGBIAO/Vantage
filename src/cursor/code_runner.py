import subprocess
import os


def run_code(file_path, language):
    """
    根据文件类型运行代码，捕获并返回错误信息。

    :param file_path: 代码文件路径
    :param language: 编程语言，决定使用哪个编译器或解释器
    :return: 运行或编译的输出和错误信息
    """
    try:
        if language.lower() == "python":
            result = subprocess.run(
                ["python", file_path],
                capture_output=True,
                text=True,
                timeout=10
            )
        elif language.lower() == "c++":
            executable = file_path.replace(".cpp", "")
            compile_process = subprocess.run(
                ["g++", file_path, "-o", executable],
                capture_output=True,
                text=True,
                timeout=10
            )
            if compile_process.returncode != 0:
                return compile_process.stdout, compile_process.stderr
            result = subprocess.run(
                [executable],
                capture_output=True,
                text=True,
                timeout=10
            )
        elif language.lower() == "cuda":
            executable = file_path.replace(".cu", "")
            compile_process = subprocess.run(
                ["nvcc", file_path, "-o", executable],
                capture_output=True,
                text=True,
                timeout=10
            )
            if compile_process.returncode != 0:
                return compile_process.stdout, compile_process.stderr
            result = subprocess.run(
                [executable],
                capture_output=True,
                text=True,
                timeout=10
            )
        else:
            return "", f"不支持的语言类型: {language}"

        return result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        return "", "运行超时，可能是死循环或计算时间过长。"
    except Exception as e:
        return "", str(e)


if __name__ == "__main__":
    # 示例：运行一个 Python 文件

    # 获取当前脚本文件所在的目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = "../../tests/code_folder/main.py"  # 替换为你的文件路径
    abs_file_path = os.path.join(script_dir, file_path)
    language = "Python"  # 或 C++, CUDA
    stdout, stderr = run_code(abs_file_path, language)

    if stderr:
        print(f"运行时错误:\n{stderr}")
    else:
        print(f"运行成功:\n{stdout}")
