import re

from openai import APIError, RateLimitError, Timeout

from src.services.tracked_openai_client import TrackedOpenAIClient


def add_function_code_with_ai(code, language, client, golbal_model=None):
    """
    使用 AI 模型为代码增加一个新功能，并返回修改后的完整代码。
    """
    prompt = (
        f"你是一名资深 {language} 工程师。请在下面这段代码上增加一个合理的新功能。\n"
        "要求生成的代码可以直接运行，并在改动处加入简短注释说明修改内容。\n"
        "请只返回完整代码。\n\n"
        f"代码:\n{code}\n"
    )

    modified_code = ""
    tracked_client = TrackedOpenAIClient(
        client=client,
        source="cursor",
        entrypoint="src/cursor/code_adder.py",
    )

    try:
        response = tracked_client.create_chat_completion(
            model=golbal_model,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
            max_tokens=4096,
            temperature=1.0,
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
