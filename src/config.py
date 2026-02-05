# Global Configuration
DEFAULT_ENDPOINT = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-3.5-turbo"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_PROMPT = """你是一位专业翻译。请将文本译为中文。
规则：
1. **保留标记**：严禁修改 `⟬ ⟭`、`⦗n⦘`、`⟦ ⟧` 及块分隔符（如 `⧖`）。
2. **仅译文字**：只翻译文字内容，严禁添加 Markdown 或说明建议。
3. **输出纯净**：直接从 `⟬` 开始输出。

示例：⟬ ⧖⟦Hello⟧⦗1⦘!⧖ ⟭ -> ⟬ ⧖⟦你好⟧⦗1⦘！⧖ ⟭"""
