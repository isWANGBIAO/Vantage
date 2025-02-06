from output_model import print_model_name
from manager.manager_main import manager
from dotenv import load_dotenv
from openai import OpenAI
import json
from datetime import datetime
import schedule
import subprocess
import os

# cursor/code_runner.py
import time


class CodeRunner:
    def run_code(self):
        for i in range(3):
            yield f'Cursor 正在处理代码：第 {i + 1}/3 步'
            time.sleep(0.5)
        yield 'Cursor 代码处理完成！'


def cursor():
    max_attempts = 1000  # 每个文件最大尝试修正次数
    # 获取当前脚本文件所在的目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    directory = "../tests/code_folder"  # 这里替换成你的目标目录
    # 将相对路径转换为绝对路径
    abs_directory = os.path.join(script_dir, directory)
    language = "Python"  # 用户指定语言
    extensions = [".py"]  # 根据语言设置扩展名

    # 设置 API 密钥和基础 URL
    # 加载.env文件
    load_dotenv()

    # 使用阿里云的API Key和URL
    print("Using Aliyun API Key and URL")
    api_key = os.getenv('ALIYUN_ACCESS_KEY')
    url = os.getenv('ALIYUN_ACCESS_BASE_URL')
    golbal_model = 'deepseek-r1'
    golbal_model = 'qwen-max-latest'

    # 使用硅基流动的API Key和URL
    # print("Using SiliconFLow API Key and URL")
    # api_key = os.getenv('API_KEY')
    # url = os.getenv('API_BASE_URL')
    # golbal_model = 'deepseek-ai/DeepSeek-R1'
    # golbal_model = 'deepseek-ai/DeepSeek-V3'
    # golbal_model = 'Qwen/Qwen2.5-Coder-32B-Instruct'
    # golbal_model = 'Qwen/Qwen2.5-72B-Instruct-128K'

    # 使用DeepSeek的API Key和URL
    print("Using DeepSeek API Key and URL")
    api_key = os.getenv('DEEPSEEK_API_KEY')
    url = os.getenv('DEEPSEEK_API_BASE_URL')
    golbal_model = 'deepseek-chat'
    golbal_model = 'deepseek-reasoner'

    # 检查API Key和URL是否成功加载
    if not api_key or not url:
        raise ValueError("API_KEY or API_BASE_URL not found in .env file")

    # 创建OpenAI客户端实例
    client = OpenAI(
        base_url=url,
        api_key=api_key
    )
    # 尽可能使用大模型以获得更好的结果

    print_model_name(client, golbal_model)

    # 调用处理文件的函数
    # process_files(abs_directory, extensions, language, max_attempts, client, golbal_model)


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
