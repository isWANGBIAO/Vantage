from openai import OpenAI  # 使用openai库
from openai import APIError, Timeout, RateLimitError  # 直接导入异常类
import re  # 使用正则表达式提取代码块


def add_function_code_with_ai(code, language, client, golbal_model=None):
    """
    使用AI模型对代码进行增加功能。
    """

    prompt = (
        f"你是一个资深{language}编程的产品经理，请你富有创意地为这款程序额外增加一个功能。"
        "确保它可以成功运行，并在修改的地方添加注释说明修改内容,在代码最前面注释说明代码是做什么的\n\n"
        f"代码:\n{code}\n\n"
        "请直接返回完整的修改后代码。"
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
            temperature=1.0  # 稍微提高创造性以应对复杂错误  # 控制输出的随机性，0 是最确定，1 更有创意
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
