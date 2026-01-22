"""影片視覺分析服務 (使用 MiniCPM-V)"""

import asyncio
import base64
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import ollama

from app.config import settings


logger = logging.getLogger(__name__)


@dataclass
class FrameDescription:
    """單幀描述"""
    timestamp: float
    description: str


@dataclass
class VisualAnalysisResult:
    """視覺分析結果"""
    success: bool
    frame_descriptions: Optional[List[FrameDescription]] = None
    overall_visual_summary: Optional[str] = None
    error_message: Optional[str] = None


class VideoVisualAnalyzer:
    """
    影片視覺分析器
    
    使用 FFmpeg 截取關鍵幀，MiniCPM-V 進行圖片理解
    """
    
    # 最大截取幀數
    MAX_FRAMES = 10
    
    # 最小截取幀數
    MIN_FRAMES = 8
    
    # 並行分析幀數（設為 1 則順序處理，設為 2-4 可並行加速）
    PARALLEL_ANALYSIS = 3
    
    def __init__(self):
        self.temp_dir = settings.temp_video_path
        self.vision_model = settings.ollama_vision_model

    def _get_video_duration(self, video_path: Path) -> float:
        """
        使用 FFprobe 取得影片長度（秒）
        """
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return float(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError) as e:
            logger.warning(f"無法取得影片長度: {e}，使用預設 30 秒")
            return 30.0

    def _calculate_frame_count(self, duration: float) -> int:
        """
        根據影片長度動態計算幀數
        
        規則：
        - 0-30 秒：8 幀
        - 30-60 秒：9 幀
        - 60+ 秒：10 幀
        """
        if duration <= 30:
            return self.MIN_FRAMES  # 8 幀
        elif duration <= 60:
            return 9
        else:
            return self.MAX_FRAMES  # 10 幀

    def _extract_frames(self, video_path: Path) -> List[Path]:
        """
        使用 FFmpeg 從影片中截取關鍵幀
        
        Args:
            video_path: 影片路徑
            
        Returns:
            截取的幀圖片路徑列表
        """
        frames_dir = self.temp_dir / f"frames_{video_path.stem}"
        frames_dir.mkdir(parents=True, exist_ok=True)
        
        # 取得影片長度並計算幀數
        duration = self._get_video_duration(video_path)
        frame_count = self._calculate_frame_count(duration)
        
        # 計算 fps（確保均勻分佈在整部影片）
        fps = frame_count / duration if duration > 0 else 0.5
        
        logger.info(f"影片長度: {duration:.1f} 秒，截取 {frame_count} 幀 (fps={fps:.3f})")
        
        # 使用 FFmpeg 截取幀
        output_pattern = str(frames_dir / "frame_%03d.jpg")
        
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vf", f"fps={fps}",
            "-frames:v", str(frame_count),
            "-q:v", "2",  # 高品質
            output_pattern,
            "-y",  # 覆蓋現有檔案
            "-loglevel", "error"
        ]
        
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg 截幀失敗: {e.stderr.decode()}")
            return []
        
        # 收集截取的幀
        frames = sorted(frames_dir.glob("frame_*.jpg"))
        logger.info(f"已截取 {len(frames)} 幀")
        
        return frames

    def _image_to_base64(self, image_path: Path) -> str:
        """將圖片轉換為 base64"""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _analyze_frame_sync(self, image_path: Path, frame_index: int, total_frames: int, duration: float) -> FrameDescription:
        """同步分析單幀"""
        try:
            # 計算時間戳（根據幀在影片中的位置）
            timestamp = (frame_index / total_frames) * duration if total_frames > 0 else 0
            
            # 使用 MiniCPM-V 分析圖片
            response = ollama.chat(
                model=self.vision_model,
                messages=[
                    {
                        "role": "user",
                        "content": """請用繁體中文描述這張圖片的主要內容。

特別注意：
1. 如果圖片中有列表、表格、清單，請完整列出所有項目
2. 如果有提到工具、技能、軟體名稱，請逐一列出
3. 如果有步驟或流程，請按順序說明
4. 如果有數字、統計資料，請精確記錄

請盡可能詳細擷取圖片中的所有文字資訊。""",
                        "images": [str(image_path)]
                    }
                ],
                options={
                    "temperature": 0.3,
                    "num_predict": 500,
                }
            )
            
            description = response["message"]["content"].strip()
            
            return FrameDescription(
                timestamp=timestamp,
                description=description
            )
            
        except Exception as e:
            logger.error(f"分析幀 {frame_index} 失敗: {e}")
            timestamp = (frame_index / total_frames) * duration if total_frames > 0 else 0
            return FrameDescription(
                timestamp=timestamp,
                description="[無法分析]"
            )

    def _cleanup_frames(self, frames: List[Path]) -> None:
        """清理截取的幀"""
        for frame in frames:
            try:
                frame.unlink()
            except Exception:
                pass
        
        # 嘗試刪除目錄
        if frames:
            try:
                frames[0].parent.rmdir()
            except Exception:
                pass

    async def analyze(self, video_path: Path) -> VisualAnalysisResult:
        """
        分析影片視覺內容
        
        Args:
            video_path: 影片檔案路徑
            
        Returns:
            VisualAnalysisResult: 視覺分析結果
        """
        try:
            # 取得影片長度
            duration = self._get_video_duration(video_path)
            
            # 截取關鍵幀
            logger.info("正在截取影片關鍵幀...")
            frames = self._extract_frames(video_path)
            
            if not frames:
                return VisualAnalysisResult(
                    success=False,
                    error_message="無法從影片截取幀"
                )
            
            # 分析每一幀（並行處理）
            total_frames = len(frames)
            logger.info(f"正在並行分析 {total_frames} 個關鍵幀（並行度: {self.PARALLEL_ANALYSIS}）...")
            loop = asyncio.get_event_loop()
            
            # 使用 Semaphore 控制並行數量
            semaphore = asyncio.Semaphore(self.PARALLEL_ANALYSIS)
            
            async def analyze_with_limit(i: int, frame_path: Path):
                async with semaphore:
                    desc = await loop.run_in_executor(
                        None, self._analyze_frame_sync, frame_path, i, total_frames, duration
                    )
                    logger.info(f"  幀 {i+1}/{total_frames}: {desc.description[:30]}...")
                    return (i, desc)
            
            # 並行分析所有幀
            tasks = [analyze_with_limit(i, fp) for i, fp in enumerate(frames)]
            results = await asyncio.gather(*tasks)
            
            # 按原始順序排列結果
            frame_descriptions = [desc for _, desc in sorted(results, key=lambda x: x[0])]
            
            # 生成整體視覺摘要
            visual_texts = [
                f"[{fd.timestamp:.0f}秒] {fd.description}" 
                for fd in frame_descriptions
            ]
            overall_summary = "\n".join(visual_texts)
            
            # 清理暫存幀
            self._cleanup_frames(frames)
            
            logger.info("視覺分析完成")
            
            return VisualAnalysisResult(
                success=True,
                frame_descriptions=frame_descriptions,
                overall_visual_summary=overall_summary
            )
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"視覺分析失敗: {error_msg}")
            
            return VisualAnalysisResult(
                success=False,
                error_message=f"視覺分析失敗: {error_msg}"
            )
