# Qwen3.8 与 Vantage 请求参数核对

日期：2026-08-20

## 主要来源

- Qwen3.8-27B 模型卡：https://huggingface.co/Qwen/Qwen3.8-27B
- SGLang OpenAI API reasoning 文档：https://github.com/sgl-project/sglang/blob/main/docs_new/docs/basic_usage/openai_api_completions.mdx
- SGLang EOS/正文为空问题：https://github.com/sgl-project/sglang/issues/24839
- SGLang thinking_budget 不生效问题：https://github.com/sgl-project/sglang/issues/25536

## 结论摘要

Qwen3.8 模型卡建议思考模式使用 temperature=1.0、top_p=0.95、top_k=20、presence_penalty=0、repetition_penalty=1；默认 reasoning_effort 为 xhigh，支持 xhigh/medium/low，并建议显式保留 thinking 上下文。

Vantage 当前通用请求在 `src/services/llm_client.py` 中发送 temperature=0.6、top_p=0.7、frequency_penalty=0.5，未发送 top_k、repetition_penalty、chat_template_kwargs 或 max_tokens。DeepSeek 有专门的采样参数清理，但 Qwen3.8 没有同等覆盖。该差异足以构成首要 A/B 假设，但还需用同一提示和同一服务实测确认。

SGLang 的公开问题记录显示，Qwen3 系列在 reasoning parser 下可能在思考阶段遇到 EOS，导致全部输出进入 reasoning_content、content 为空；另有记录显示 thinking_budget 可能不生效并耗尽 max_tokens。因此即使参数修正，仍需检查服务端 SGLang 版本、reasoning parser 和输出上限。
