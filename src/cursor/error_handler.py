from openai import OpenAI  # 使用openai库
from openai import APIError, Timeout, RateLimitError  # 直接导入异常类
import re  # 使用正则表达式提取代码块
import os  # 使用os库获取环境变量


def analyze_error_with_ai(code, error_message, language, client=None, golbal_model=None):
    """
    使用AI分析错误信息，提供代码修改建议。

    :param code: 原始代码内容
    :param error_message: 编译或运行时的错误信息
    :param language: 编程语言
    :return: 修改后的代码
    """
    prompt = (
        f"你是一个资深的{language}开发者。以下是运行时或编译时的错误信息，请根据错误信息修复代码，并一定要发挥你的想象增加一个功能"
        "确保它能够成功运行，并在修改的地方添加注释说明修改内容,在代码最前面注释说明代码是做什么的\n\n"
        f"错误信息:\n{error_message}\n\n"
        f"代码:\n{code}\n\n"
        "请返回完整的修改后代码。"
    )

    # 用try except捕获异常
    try:
        response = client.chat.completions.create(
            model=golbal_model,  # 指定模型
            messages=[
                {'role': 'user',
                 'content': prompt},
            ],
            stream=True,  # 使用流式传输获取响应
            max_tokens=4096,  # 输出的最大 token 数
            temperature=0.2  # 稍微提高创造性以应对复杂错误  # 控制输出的随机性，0 是最确定，1 更有创意
        )

        modified_code = []
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                modified_code.append(content)
                print(content, end='', flush=True)  # 实时显示进度

        full_code = ''.join(modified_code).strip()

        # 提取代码块（防止模型添加额外解释）
        code_match = re.search(r'```python\n(.*?)\n```', full_code, re.DOTALL)
        if code_match:
            modified_code = code_match.group(1)
        else:
            modified_code = full_code  # 如果没有代码块标记则返回全部内容
        print("\n---------------\n：")
        print("AI修改后的代码：")
        print(modified_code)
        print("\n---------------\n：")

    except APIError as e:
        print(f"API error: {e}")
    except Timeout as e:
        print(f"Request timed out: {e}")
    except RateLimitError as e:
        print(f"Rate limit exceeded: {e}")
    return modified_code


if __name__ == "__main__":
    # 示例：假设有一个简单的Python错误
    sample_code = """
def add_numbers(a, b)
    return a + b
print(add_numbers(5, 10))
"""
    sample_error = "SyntaxError: expected ':' at line 2"
    language = "Python"

    modified_code = analyze_error_with_ai(sample_code, sample_error, language)
    print("AI修改后的代码:\n", modified_code)
