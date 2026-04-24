import time

from src.services.tracked_openai_client import TrackedOpenAIClient


def print_model_name(client, golbal_model):
    try:
        print("Using model: " + golbal_model)
        start_time = time.time()
        tracked_client = TrackedOpenAIClient(
            client=client,
            source="output_model",
            entrypoint="src/output_model.py",
        )
        completion = tracked_client.create_chat_completion(
            model=golbal_model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {
                    "role": "user",
                    "content": "你是什么模型？你的资料的最新日期是什么？你的最大上下文是多少个token，为多少K？",
                },
            ],
        )
        latency = time.time() - start_time

        print(completion.choices[0].message.content)

        total_tokens = completion.usage.total_tokens if hasattr(completion, "usage") else "N/A"
        if total_tokens != "N/A" and latency > 0:
            tokens_per_second = total_tokens / latency
        else:
            tokens_per_second = "N/A"

        print(f"Latency: {latency:.2f} seconds")
        print(f"Total Tokens Used: {total_tokens}")
        print(
            "Tokens per Second: "
            f"{tokens_per_second if tokens_per_second == 'N/A' else f'{tokens_per_second:.2f} tokens/sec'}"
        )

    except Exception as e:
        print(f"An error occurred: {e}")
