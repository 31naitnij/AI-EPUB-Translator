import json
import os
import sys


class ConfigManager:
    def __init__(self, config_path=None):
        # 自动选择可写的绝对路径，避免依赖当前工作目录 (CWD)
        # 优先级:
        #   1. 调用方显式传入的 config_path
        #   2. 程序所在目录 (源码模式: main.py 同目录; 打包模式: exe 同目录)
        #   3. 用户主目录下的应用配置目录 (回退方案, 用于程序目录不可写的情况)
        if config_path:
            self.config_path = os.path.abspath(config_path)
        else:
            self.config_path = self._resolve_writable_config_path()
        self.config = self.load_config()

    @staticmethod
    def _get_app_dir():
        """获取程序所在目录 (源码模式返回 main.py 目录, 打包模式返回 exe 目录)"""
        if getattr(sys, 'frozen', False):
            # PyInstaller 打包模式
            return os.path.dirname(os.path.abspath(sys.executable))
        # 源码模式: main.py 所在目录 (src/core/config_manager.py 上两级)
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    @classmethod
    def _resolve_writable_config_path(cls):
        app_dir = cls._get_app_dir()
        primary = os.path.join(app_dir, "config.json")

        # 若已存在且可写, 直接使用
        if os.path.exists(primary):
            if os.access(primary, os.W_OK):
                return primary
        else:
            # 不存在, 检查父目录是否可写
            if os.access(app_dir, os.W_OK):
                return primary

        # 回退: 用户主目录下的应用配置目录
        if sys.platform == 'win32':
            base = os.environ.get('APPDATA') or os.path.expanduser('~')
            fallback_dir = os.path.join(base, 'EPUB_Translator')
        else:
            fallback_dir = os.path.join(os.path.expanduser('~'), '.config', 'EPUB_Translator')

        try:
            os.makedirs(fallback_dir, exist_ok=True)
        except OSError:
            # 最后兜底: 仍用相对路径 (维持旧行为)
            return "config.json"

        fallback = os.path.join(fallback_dir, 'config.json')

        # 迁移旧配置 (如果程序目录下的 config.json 存在但不可写, 复制一份到回退位置)
        if os.path.exists(primary) and not os.path.exists(fallback):
            try:
                import shutil
                shutil.copy2(primary, fallback)
            except OSError:
                pass

        return fallback

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {"history": []}
        return {"history": []}

    def save_config(self, settings):
        # settings should be a dict: {api_key, api_url, model, temp, prompt, chunk_size}
        # Check if already in history, if so, move to top
        history = self.config.get("history", [])
        
        # Remove if already exists (matching by some key fields)
        history = [h for h in history if not (h.get('api_key') == settings.get('api_key') and h.get('api_url') == settings.get('api_url'))]
        
        # Add to top
        history.insert(0, settings)
        
        # Limit history to 10 items
        self.config["history"] = history[:10]
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def set_value(self, key, value):
        self.config[key] = value
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def get_value(self, key, default=None):
        return self.config.get(key, default)

    def get_history(self):
        return self.config.get("history", [])

    def get_last_settings(self):
        history = self.get_history()
        return history[0] if history else {}
