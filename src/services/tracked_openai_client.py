import logging
import time
import uuid

from src.services.model_call_recorder import SessionRecorder


def _usage_to_dict(usage):
    if usage is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    if isinstance(usage, dict):
        return {
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        }

    return {
        "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
        "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
    }


def _extract_message_content(response):
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return getattr(message, "content", "") or ""


class _TrackedStream:
    def __init__(
        self,
        raw_stream,
        *,
        recorder,
        call_id,
        model,
        provider_route,
        reasoning_effort,
        start_time,
    ):
        self._raw_stream = iter(raw_stream)
        self._recorder = recorder
        self._call_id = call_id
        self._model = model
        self._provider_route = provider_route
        self._reasoning_effort = reasoning_effort
        self._start_time = start_time
        self._content_parts = []
        self._usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        self._finished = False
        self._first_token_latency = None

    def __iter__(self):
        return self

    def __next__(self):
        try:
            chunk = next(self._raw_stream)
        except StopIteration:
            self._finalize_success()
            raise
        except Exception as error:
            self._finalize_error(error)
            raise

        usage = getattr(chunk, "usage", None)
        if usage is not None:
            self._usage = _usage_to_dict(usage)

        choices = getattr(chunk, "choices", None) or []
        if choices:
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", "") if delta else ""
            if content:
                if self._first_token_latency is None:
                    self._first_token_latency = time.time() - self._start_time
                self._content_parts.append(content)

        return chunk

    def _safe_record(self, method_name, **kwargs):
        if self._recorder is None:
            return
        try:
            getattr(self._recorder, method_name)(**kwargs)
        except Exception as error:
            logging.error("Failed to persist tracked OpenAI stream via %s: %s", method_name, error)

    def _finalize_success(self):
        if self._finished:
            return
        self._finished = True
        duration = time.time() - self._start_time
        content = "".join(self._content_parts)
        self._safe_record(
            "record_request_completed",
            call_id=self._call_id,
            model=self._model,
            provider_route=self._provider_route,
            stream=True,
            reasoning_effort=self._reasoning_effort,
            content=content,
            thinking="",
            usage=self._usage,
            duration=duration,
            first_token_latency=self._first_token_latency,
        )
        self._safe_record(
            "record_token_count",
            call_id=self._call_id,
            last_token_usage=self._usage,
        )

    def _finalize_error(self, error):
        if self._finished:
            return
        self._finished = True
        self._safe_record(
            "record_request_failed",
            call_id=self._call_id,
            error=error,
            model=self._model,
            provider_route=self._provider_route,
            stream=True,
            reasoning_effort=self._reasoning_effort,
            duration=time.time() - self._start_time,
        )


class TrackedOpenAIClient:
    def __init__(
        self,
        *,
        client,
        source,
        entrypoint,
        history_dir=None,
        session_id=None,
        context_file=None,
        provider_route="openai_sdk",
        base_url=None,
    ):
        self.client = client
        self.source = source
        self.entrypoint = entrypoint
        self.provider_route = provider_route
        self.base_url = base_url
        self.recorder = self._build_recorder(
            session_id=session_id,
            history_dir=history_dir,
            context_file=context_file,
        )

    def _build_recorder(self, *, session_id, history_dir, context_file):
        try:
            return SessionRecorder(
                session_id=session_id,
                source=self.source,
                entrypoint=self.entrypoint,
                history_dir=history_dir,
                context_file=context_file,
                provider_route=self.provider_route,
                base_url=self.base_url,
            )
        except Exception as error:
            logging.error("Failed to initialize tracked OpenAI SessionRecorder: %s", error)
            return None

    def _safe_record(self, method_name, **kwargs):
        if self.recorder is None:
            return
        try:
            getattr(self.recorder, method_name)(**kwargs)
        except Exception as error:
            logging.error("Failed to persist tracked OpenAI call via %s: %s", method_name, error)

    def create_chat_completion(
        self,
        *,
        model,
        messages,
        stream=False,
        reasoning_effort="medium",
        metadata=None,
        **kwargs,
    ):
        call_id = str(uuid.uuid4())
        start_time = time.time()

        self._safe_record(
            "record_request_started",
            call_id=call_id,
            model=model,
            provider_route=self.provider_route,
            stream=stream,
            reasoning_effort=reasoning_effort,
            messages=None,
            metadata=metadata,
        )
        self._safe_record(
            "record_message_snapshot",
            call_id=call_id,
            messages=messages,
        )

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=stream,
                **kwargs,
            )
        except Exception as error:
            self._safe_record(
                "record_request_failed",
                call_id=call_id,
                error=error,
                model=model,
                provider_route=self.provider_route,
                stream=stream,
                reasoning_effort=reasoning_effort,
                duration=time.time() - start_time,
            )
            raise

        if stream:
            return _TrackedStream(
                response,
                recorder=self.recorder,
                call_id=call_id,
                model=model,
                provider_route=self.provider_route,
                reasoning_effort=reasoning_effort,
                start_time=start_time,
            )

        usage = _usage_to_dict(getattr(response, "usage", None))
        self._safe_record(
            "record_request_completed",
            call_id=call_id,
            model=model,
            provider_route=self.provider_route,
            stream=False,
            reasoning_effort=reasoning_effort,
            content=_extract_message_content(response),
            thinking="",
            usage=usage,
            duration=time.time() - start_time,
            first_token_latency=None,
        )
        self._safe_record(
            "record_token_count",
            call_id=call_id,
            last_token_usage=usage,
        )
        return response
