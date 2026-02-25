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
            try:
                # 1. Try Doubao-style nested object
                return do_request(extra_body={"thinking": {"type": "disabled"}})
            except Exception as e1:
                # 2. Try string style as fallback
                if any(x in str(e1) for x in ["400", "BadRequest", "InvalidParameter"]):
                    try:
                        return do_request(extra_body={"thinking": "disabled"})
                    except Exception as e2:
                        # 3. Final fallback: retry without thinking parameter
                        if any(x in str(e2) for x in ["400", "BadRequest", "InvalidParameter"]):
                            return do_request(extra_body=None)
                        else:
                            raise e2
                else:
                    raise e1
        except Exception as e:
            print(f"翻译出错: {e}")
            return f"[翻译错误: {e}]"
