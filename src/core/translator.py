from openai import OpenAI
import json

class Translator:
    def __init__(self, api_key, base_url, model, temperature, system_prompt, timeout=60):
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=float(timeout))
        self.model = model
        self.temperature = float(temperature)
        self.system_prompt = system_prompt
        self.timeout = float(timeout)

    def translate_chunk(self, current_text):
        messages = [
            {"role": "system", "content": self.system_prompt}
        ]
        
        # Removed multi-turn dialogue context (history)
        
        # Append Stop Symbol to user content
        messages.append({"role": "user", "content": f"{current_text}⏹️"})
        
        try:
            try:
                # 1. Try Doubao-style nested object (Standard for newer models)
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    stream=False,
                    stop=["⏹️"],
                    extra_body={
                        "thinking": {"type": "disabled"}
                    }
                )
            except Exception as e1:
                # 2. Try string style as fallback
                if "400" in str(e1) or "BadRequest" in str(e1) or "InvalidParameter" in str(e1):
                    try:
                        response = self.client.chat.completions.create(
                            model=self.model,
                            messages=messages,
                            temperature=self.temperature,
                            stream=False,
                            stop=["⏹️"],
                            extra_body={
                                "thinking": "disabled"
                            }
                        )
                    except Exception as e2:
                        # 3. Final fallback: retry without thinking parameter
                        if "400" in str(e2) or "BadRequest" in str(e2) or "InvalidParameter" in str(e2):
                            response = self.client.chat.completions.create(
                                model=self.model,
                                messages=messages,
                                temperature=self.temperature,
                                stream=False,
                                stop=["⏹️"]
                            )
                        else:
                            raise e2
                else:
                    raise e1

            # Non-streaming return
            return response.choices[0].message.content
        except Exception as e:
            print(f"翻译出错: {e}")
            return f"[翻译错误: {e}]"
