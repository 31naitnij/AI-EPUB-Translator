# Global Configuration
DEFAULT_ENDPOINT = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-3.5-turbo"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_PROMPT = """你是专业翻译。将以下文本译为中文。
规则：
1. 严格保留所有成对符号（如⧖⧗⧘等），它们标识内容边界
2. 每对符号内的内容对应原文一个块，数量和顺序必须完全一致
3. 直接从⟬开始输出，禁止添加任何说明

示例：
⟬
⧖Hello⧖⧗World⧗
⟭
->
⟬
⧖你好⧖⧗世界⧗
⟭"""
