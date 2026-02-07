# Global Configuration
DEFAULT_ENDPOINT = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-3.5-turbo"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_PROMPT = """你是专业翻译。将以下文本译为中文。
规则：
1. 严格保留所有特殊成对符号（如⩀⩁等标识块，⭀⭁等标识块内标签），它们是结构锚点
2. 每个⩀...⩀对应一个翻译块，数量和顺序必须与原文完全一致
3. 保持标签符号（如⭀文字⭀）在块内的相对位置，仅翻译其中的文字
4. 直接输出翻译内容，不要有任何额外解释

示例：
⩀Hello⩀
⩁The ⭀World⭀⩁
->
⩀你好⩀
⩁这个⭀世界⭀⩁"""
