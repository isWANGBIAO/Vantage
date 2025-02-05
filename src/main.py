import time
import schedule
from datetime import datetime
import json
import os
from cursor.process import process_files
from openai import OpenAI
from dotenv import load_dotenv
from manager.manager_main import manager
from output_model import print_model_name


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


def main():
    cursor()
    manager()
    # 设计程序每日最多1GB的内容。


if __name__ == "__main__":
    main()
