import re

from openai import APIError, RateLimitError, Timeout

from src.services.tracked_openai_client import TrackedOpenAIClient


def analyze_error_with_ai(code, error_message, language, client=None, golbal_model=None):
    """
    使用 AI 分析错误并返回修复后的代码建议。
    """
    prompt = (
        f"你是一名资深 {language} 工程师。下面是运行或编译错误信息，请根据错误修复代码，"
        "并在合理范围内提升代码质量。\n"
        "要求生成的代码可以直接运行，并在关键改动处加入简短注释说明修改内容。\n"
        "请只返回完整代码。\n\n"
        f"错误信息:\n{error_message}\n\n"
        f"代码:\n{code}\n"
    )

    modified_code = ""
    tracked_client = TrackedOpenAIClient(
        client=client,
        source="cursor",
        entrypoint="src/cursor/error_handler.py",
    )

    try:
        response = tracked_client.create_chat_completion(
            model=golbal_model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            max_tokens=4096,
            temperature=0.2,
        )

        content_parts = []
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                content_parts.append(content)
                print(content, end="", flush=True)

        full_code = "".join(content_parts).strip()
        code_match = re.search(r"```(?:python)?\n(.*?)\n```", full_code, re.DOTALL)
        if code_match:
            modified_code = code_match.group(1)
        else:
            modified_code = full_code

        print("\n---------------\n")
        print("AI 修改后的代码:")
        print(modified_code)
        print("\n---------------\n")

    except APIError as e:
        print(f"API error: {e}")
    except Timeout as e:
        print(f"Request timed out: {e}")
    except RateLimitError as e:
        print(f"Rate limit exceeded: {e}")

    return modified_code


if __name__ == "__main__":
    sample_code = """
def add_numbers(a, b)
    return a + b
print(add_numbers(5, 10))
"""
    sample_error = "SyntaxError: expected ':' at line 2"
    language = "Python"

    modified_code = analyze_error_with_ai(sample_code, sample_error, language)
    print("AI 修改后的代码:\n", modified_code)
