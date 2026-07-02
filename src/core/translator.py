from openai import OpenAI
import json
import re
import time
import threading


class RateLimiter:
    def __init__(self, interval=0, batch_size=1):
        self.interval = float(interval)
        self.batch_size = int(batch_size)
        self.lock = threading.Lock()
        self.window_start = 0.0
        self.tokens_used = 0

    def set_params(self, interval, batch_size=1):
        with self.lock:
            self.interval = float(interval)
            self.batch_size = int(batch_size)

    def acquire(self):
        if self.interval <= 0 or self.batch_size <= 0:
            return
        while True:
            wait_until = 0.0
            with self.lock:
                now = time.monotonic()
                if self.window_start == 0.0:
                    self.window_start = now
                if now >= self.window_start + self.interval:
                    self.window_start = now
                    self.tokens_used = 0
                if self.tokens_used < self.batch_size:
                    self.tokens_used += 1
                    return
                wait_until = self.window_start + self.interval
            wait_time = wait_until - time.monotonic()
            if wait_time > 0:
                time.sleep(wait_time)


THINK_TAGS = ['thought', 'think', 'thinking', 'reasoning', 'cot', 'scratchpad', 'reflection', 'analysis']


def _remove_closed_tags(text):
    tag_pattern = '|'.join(THINK_TAGS)
    open_re = re.compile(rf'<({tag_pattern})\b[^>]*>', re.IGNORECASE)
    prev = None
    while prev != text:
        prev = text
        result = []
        i = 0
        while i < len(text):
            m = open_re.search(text, i)
            if not m:
                result.append(text[i:])
                break
            result.append(text[i:m.start()])
            tag_name = m.group(1).lower()
            close_re = re.compile(rf'</{tag_name}>', re.IGNORECASE)
            close_m = close_re.search(text, m.end())
            if close_m:
                i = close_m.end()
            else:
                result.append(text[m.start():])
                break
        text = ''.join(result)
    return text


def _find_first_unclosed_tag(text):
    tag_pattern = '|'.join(THINK_TAGS)
    open_re = re.compile(rf'<({tag_pattern})\b[^>]*>', re.IGNORECASE)
    lower_text = text.lower()
    first_pos = len(text)
    pos = 0
    while pos < len(text):
        m = open_re.search(text, pos)
        if not m:
            break
        tag_name = m.group(1).lower()
        close_tag_lower = f'</{tag_name}>'
        close_start = lower_text.find(close_tag_lower, m.end())
        if close_start == -1:
            if m.start() < first_pos:
                first_pos = m.start()
            break
        pos = close_start + len(close_tag_lower)
    return first_pos


def strip_thinking_tags(text, stream_mode=False):
    if not text:
        return text
    cleaned = _remove_closed_tags(text)
    if stream_mode:
        cut_pos = _find_first_unclosed_tag(cleaned)
        cleaned = cleaned[:cut_pos]
    cleaned = re.sub(r'[ \t]*\n[ \t]*\n[ \t]*\n+', '\n\n', cleaned)
    cleaned = re.sub(r'^(\s*\n)+', '', cleaned)
    cleaned = re.sub(r'(\s*\n)+$', '', cleaned)
    return cleaned


class Translator:
    def __init__(self, api_key, base_url, model, temperature, system_prompt, timeout=60):
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=float(timeout))
        self.model = model
        self.temperature = float(temperature)
        self.system_prompt = system_prompt
        self.timeout = float(timeout)

    def translate_chunk(self, current_text, stream_callback=None):
        messages = [
            {"role": "system", "content": self.system_prompt}
        ]

        # Append Stop Symbol to user content
        messages.append({"role": "user", "content": f"{current_text}⏹️"})

        def do_request(extra_body=None):
            if stream_callback:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    stream=True,
                    stop=["⏹️"],
                    extra_body=extra_body
                )
                full_content = ""
                for chunk in response:
                    if isinstance(chunk, str):
                        raise APIResponseError(
                            "流式响应返回了字符串而非标准 SSE chunk",
                            raw_response=chunk,
                            content_type="text/plain (stream)",
                            status_code=None,
                        )
                    if not getattr(chunk, "choices", None):
                        continue
                    delta = chunk.choices[0].delta.content if chunk.choices else ""
                    if delta:
                        full_content += delta
                        cleaned = strip_thinking_tags(full_content, stream_mode=True)
                        if cleaned:
                            stream_callback(cleaned)
                return strip_thinking_tags(full_content)
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    stream=False,
                    stop=["⏹️"],
                    extra_body=extra_body
                )
                content = self._extract_content(response)
                return strip_thinking_tags(content)

        try:
            # Mode 0: Doubao-style nested object
            if getattr(self, '_extra_body_mode', 0) == 0:
                try:
                    res = do_request(extra_body={"thinking": {"type": "disabled"}})
                    self._extra_body_mode = 0
                    return res
                except Exception as e1:
                    # APIResponseError 是兼容性问题, 不参与 extra_body 降级, 直接抛出
                    if isinstance(e1, APIResponseError):
                        raise e1
                    if any(x in str(e1) for x in ["400", "422", "500", "502", "BadRequest", "InvalidParameter", "BadGateway", "Unprocessable"]):
                        self._extra_body_mode = 1
                    else:
                        raise e1

            # Mode 1: String style
            if getattr(self, '_extra_body_mode', 0) == 1:
                try:
                    res = do_request(extra_body={"thinking": "disabled"})
                    self._extra_body_mode = 1
                    return res
                except Exception as e2:
                    if isinstance(e2, APIResponseError):
                        raise e2
                    if any(x in str(e2) for x in ["400", "422", "500", "502", "BadRequest", "InvalidParameter", "BadGateway", "Unprocessable"]):
                        self._extra_body_mode = 2
                    else:
                        raise e2

            # Mode 2: No extra_body (Standard OpenAI)
            if getattr(self, '_extra_body_mode', 0) == 2:
                res = do_request(extra_body=None)
                self._extra_body_mode = 2
                return res

        except APIResponseError as e:
            # 兼容性问题: API 返回了非标准响应, 提供完整诊断信息
            print(f"[API 兼容性错误] {e}")
            return f"[翻译错误: API 返回非标准响应]\n{e}"
        except Exception as e:
            print(f"翻译出错: {e}")
            return f"[翻译错误: {e}]"

    @staticmethod
    def _extract_content(response):
        """
        从 chat.completions.create 的响应中提取译文文本。
        增加类型保护: 第三方 API 在异常场景可能返回字符串 (SDK 宽松降级行为),
        而非标准 ChatCompletion 对象。
        """
        # 防御 1: SDK 宽松降级返回的纯字符串 (Content-Type 非 json 时)
        if isinstance(response, str):
            raise APIResponseError(
                "API 返回了纯文本而非 ChatCompletion 对象",
                raw_response=response,
                content_type="text/plain (inferred from str return)",
                status_code=None,
            )

        # 防御 2: 有 choices 但结构异常
        choices = getattr(response, "choices", None)
        if not choices:
            # 尝试提取诊断信息
            raw = getattr(response, "model_dump", lambda: repr(response))()
            raise APIResponseError(
                "API 响应缺少 choices 字段",
                raw_response=str(raw),
                content_type=type(response).__name__,
                status_code=None,
            )

        choice = choices[0]
        message = getattr(choice, "message", None)
        if message is None:
            raise APIResponseError(
                "API 响应缺少 message 字段",
                raw_response=str(choice),
                content_type=type(response).__name__,
                status_code=None,
            )

        content = getattr(message, "content", None)
        if content is None:
            # 某些模型会返回 reasoning_content 而非 content
            reasoning = getattr(message, "reasoning_content", None)
            if reasoning:
                return reasoning
            raise APIResponseError(
                "API 响应缺少 content 字段",
                raw_response=str(message),
                content_type=type(response).__name__,
                status_code=None,
            )

        return content


class APIResponseError(Exception):
    """
    API 返回非标准响应时抛出的异常。
    携带原始响应内容、Content-Type、状态码, 便于诊断兼容性问题。
    """

    def __init__(self, message, raw_response=None, content_type=None, status_code=None):
        self.raw_response = raw_response
        self.content_type = content_type
        self.status_code = status_code

        # 截断过长的原始响应, 避免日志爆炸
        raw_preview = ""
        if raw_response is not None:
            raw_str = str(raw_response)
            if len(raw_str) > 500:
                raw_preview = raw_str[:500] + f"\n... (共 {len(raw_str)} 字符, 已截断)"
            else:
                raw_preview = raw_str

        parts = [message]
        if status_code is not None:
            parts.append(f"HTTP 状态码: {status_code}")
        if content_type is not None:
            parts.append(f"Content-Type: {content_type}")
        if raw_preview:
            parts.append(f"原始响应:\n{raw_preview}")

        super().__init__(" | ".join(parts))
