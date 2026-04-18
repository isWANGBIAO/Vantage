import re

from openai import APIError, RateLimitError, Timeout

from src.services.tracked_openai_client import TrackedOpenAIClient


def modify_code_with_ai(code, language, client, golbal_model=None):
    """
    使用 AI 模型修复并改进代码，返回修改后的完整代码。
    """
    prompt = (
        f"你是一名资深 {language} 工程师。请阅读下面的代码，修复潜在错误并提升代码质量。\n"
        "要求生成的代码可以直接运行，并在关键改动处加入简短注释说明修改内容。\n"
        "请只返回完整代码。\n\n"
        f"代码:\n{code}\n"
    )

    modified_code = ""
    tracked_client = TrackedOpenAIClient(
        client=client,
        source="cursor",
        entrypoint="src/cursor/code_modifier.py",
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

    except APIError as e:
        print(f"API error: {e}")
    except Timeout as e:
        print(f"Request timed out: {e}")
    except RateLimitError as e:
        print(f"Rate limit exceeded: {e}")

    return modified_code
