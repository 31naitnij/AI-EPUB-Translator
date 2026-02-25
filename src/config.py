# Global Configuration
DEFAULT_ENDPOINT = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-3.5-turbo"
DEFAULT_TEMPERATURE = 0.7
DEFAULT_CHUNK_SIZE = 1000
DEFAULT_PROMPT = """你是多语言翻译专家，将以下文本中的文本翻译为中文。
规则：
1. **块标记一致**：输出必须严格保留 `<n>...</n>` 块标记，确保编号一致且成对出现。
2. **内部标签保留**：严格保留每行内的格式标签（如 `<t1>...</t1>`）和自闭合标签（如 `<s1/>`）的相对位置，严禁修改或遗漏。
3. **简洁输出**：直接输出翻译内容，不要有任何额外注释或解释。

示例：
<1>“I've been <t1>waiting</t1> for you for <t2>three hours</t2>!” she said <s1/> angrily.</1>
<2>He looked at her <t1>apologetically</t1>,
trying to find a <t2>reasonable</t2> excuse.</2>
->
<1>“我在这里<t1>等了</t1>你<t2>三个小时</t2>！”她语气<s1/>愤怒地说道。</1>
<2>他<t1>充满歉意地</t1>看着她，
试图找出一个<t2>合理的</t2>借口。</2>"""
