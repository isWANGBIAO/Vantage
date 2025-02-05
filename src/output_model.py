import time


def print_model_name(client, golbal_model):
    try:
        print("Using model: " + golbal_model)
        # 记录开始时间
        start_time = time.time()
        completion = client.chat.completions.create(
            model=golbal_model,
            messages=[
                {'role': 'system', 'content': 'You are a helpful assistant.'},
                {'role': 'user', 'content': '你是什么模型？你的资料的最新日期是什么？你的最大上下文是多少个token？为多少K？'},
            ]
        )
        # 记录结束时间
        end_time = time.time()

        # 计算延迟
        latency = end_time - start_time

        print(completion.choices[0].message.content)

        # 获取 token 使用信息
        total_tokens = completion.usage.total_tokens if hasattr(completion, 'usage') else 'N/A'

        # 计算每秒处理的 token 数
        if total_tokens != 'N/A':
            tokens_per_second = total_tokens / latency
        else:
            tokens_per_second = 'N/A'

        # 输出统计信息
        print(f"Latency: {latency:.2f} seconds")
        print(f"Total Tokens Used: {total_tokens}")
        print(f"Tokens per Second: {tokens_per_second if tokens_per_second == 'N/A' else f'{tokens_per_second:.2f} tokens/sec'}")

    except Exception as e:
        print(f"An error occurred: {e}")
