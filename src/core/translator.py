from openai import OpenAI
import json

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
                    delta = chunk.choices[0].delta.content if chunk.choices else ""
                    if delta:
                        full_content += delta
                        stream_callback(full_content)
                return full_content
            else:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    stream=False,
                    stop=["⏹️"],
                    extra_body=extra_body
                )
                return response.choices[0].message.content

        try:
            # Mode 0: Doubao-style nested object
            if getattr(self, '_extra_body_mode', 0) == 0:
                try:
                    res = do_request(extra_body={"thinking": {"type": "disabled"}})
                    self._extra_body_mode = 0
                    return res
                except Exception as e1:
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
                    if any(x in str(e2) for x in ["400", "422", "500", "502", "BadRequest", "InvalidParameter", "BadGateway", "Unprocessable"]):
                        self._extra_body_mode = 2
                    else:
                        raise e2

            # Mode 2: No extra_body (Standard OpenAI)
            if getattr(self, '_extra_body_mode', 0) == 2:
                res = do_request(extra_body=None)
                self._extra_body_mode = 2
                return res

        except Exception as e:
            print(f"翻译出错: {e}")
            return f"[翻译错误: {e}]"
