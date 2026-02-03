"""Prompt 模板載入器服務

提供快取載入外部 Prompt 檔案與隨機選取範例筆記功能。
"""

import logging
import random
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PromptLoader:
    """Prompt 模板與範例載入器
    
    特點：
    - 初始化時載入所有 Prompt 與範例至快取
    - 支援依類型（audio/visual_only）隨機選取範例
    - 提供 fallback 機制確保系統穩定性
    """
    
    def __init__(self, prompts_path: str = "./app/prompts"):
        """初始化 PromptLoader
        
        Args:
            prompts_path: Prompt 資料夾根目錄路徑
        """
        self.prompts_path = Path(prompts_path)
        self._prompt_cache: Dict[str, str] = {}
        self._example_cache: Dict[str, list] = {
            "audio": [],
            "visual_only": []
        }
        
        # 初始化時載入所有內容至快取
        self._load_all_prompts()
        self._load_all_examples()
        
        logger.info(f"PromptLoader 初始化完成，載入 {len(self._prompt_cache)} 個 Prompt 模板")
        logger.info(f"範例載入：audio={len(self._example_cache['audio'])}，visual_only={len(self._example_cache['visual_only'])}")
    
    def _load_all_prompts(self) -> None:
        """載入所有 Prompt 模板至快取"""
        # 載入 system prompts
        system_dir = self.prompts_path / "system"
        if system_dir.exists():
            for file_path in system_dir.glob("*.txt"):
                key = f"system/{file_path.stem}"
                self._load_prompt_file(key, file_path)
        
        # 載入 templates
        templates_dir = self.prompts_path / "templates"
        if templates_dir.exists():
            for file_path in templates_dir.glob("*.txt"):
                key = f"templates/{file_path.stem}"
                self._load_prompt_file(key, file_path)
    
    def _load_prompt_file(self, key: str, file_path: Path) -> None:
        """載入單一 Prompt 檔案
        
        Args:
            key: 快取鍵值
            file_path: 檔案路徑
        """
        try:
            content = file_path.read_text(encoding="utf-8")
            self._prompt_cache[key] = content
            logger.debug(f"載入 Prompt: {key}")
        except Exception as e:
            logger.warning(f"載入 Prompt 失敗 {file_path}: {e}")
    
    def _load_all_examples(self) -> None:
        """載入所有範例筆記至快取"""
        examples_dir = self.prompts_path / "examples"
        
        # 載入 audio 範例
        audio_dir = examples_dir / "audio"
        if audio_dir.exists():
            for file_path in audio_dir.glob("*.md"):
                self._load_example_file("audio", file_path)
        
        # 載入 visual_only 範例
        visual_dir = examples_dir / "visual_only"
        if visual_dir.exists():
            for file_path in visual_dir.glob("*.md"):
                self._load_example_file("visual_only", file_path)
    
    def _load_example_file(self, category: str, file_path: Path) -> None:
        """載入單一範例檔案
        
        Args:
            category: 範例類別 (audio/visual_only)
            file_path: 檔案路徑
        """
        try:
            content = file_path.read_text(encoding="utf-8")
            self._example_cache[category].append({
                "name": file_path.stem,
                "content": content
            })
            logger.debug(f"載入範例: {category}/{file_path.stem}")
        except Exception as e:
            logger.warning(f"載入範例失敗 {file_path}: {e}")
    
    def load_prompt(self, name: str, fallback: Optional[str] = None) -> str:
        """從快取讀取 Prompt 模板
        
        Args:
            name: Prompt 名稱，格式為 "類型/檔名" (e.g., "templates/note_prompt")
            fallback: 若找不到時的預設值
            
        Returns:
            Prompt 內容字串
        """
        if name in self._prompt_cache:
            return self._prompt_cache[name]
        
        if fallback is not None:
            logger.warning(f"Prompt '{name}' 不存在，使用 fallback")
            return fallback
        
        logger.error(f"Prompt '{name}' 不存在且無 fallback")
        return ""
    
    def get_random_example(self, category: str) -> str:
        """依類別隨機選取一個範例筆記
        
        Args:
            category: 範例類別 ("audio" 或 "visual_only")
            
        Returns:
            隨機選取的範例筆記完整內容
        """
        examples = self._example_cache.get(category, [])
        
        if not examples:
            logger.warning(f"類別 '{category}' 無可用範例")
            return "（無可用範例）"
        
        selected = random.choice(examples)
        logger.debug(f"隨機選取範例: {category}/{selected['name']}")
        return selected["content"]
    
    def get_example_count(self, category: str) -> int:
        """取得指定類別的範例數量
        
        Args:
            category: 範例類別
            
        Returns:
            範例數量
        """
        return len(self._example_cache.get(category, []))
    
    def reload(self) -> None:
        """重新載入所有 Prompt 與範例（用於熱更新）"""
        self._prompt_cache.clear()
        self._example_cache = {"audio": [], "visual_only": []}
        self._load_all_prompts()
        self._load_all_examples()
        logger.info("PromptLoader 重新載入完成")


# 建立全域實例（延遲初始化）
_prompt_loader: Optional[PromptLoader] = None


def get_prompt_loader(prompts_path: str = "./app/prompts") -> PromptLoader:
    """取得 PromptLoader 單例
    
    Args:
        prompts_path: Prompt 資料夾路徑
        
    Returns:
        PromptLoader 實例
    """
    global _prompt_loader
    if _prompt_loader is None:
        _prompt_loader = PromptLoader(prompts_path)
    return _prompt_loader
