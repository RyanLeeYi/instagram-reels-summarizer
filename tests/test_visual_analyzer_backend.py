"""F21: VideoVisualAnalyzer backend selection and fallback tests."""

from pathlib import Path

import pytest

from app.services.antigravity_visual_analyzer import AntigravityAnalysisError
from app.services import visual_analyzer as visual_module
from app.services.visual_analyzer import VideoVisualAnalyzer


def test_video_frame_uses_antigravity_backend(monkeypatch, tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"fake")
    monkeypatch.setattr(visual_module.settings, "visual_analyzer_backend", "antigravity", raising=False)

    analyzer = VideoVisualAnalyzer()
    monkeypatch.setattr(
        analyzer.antigravity_analyzer,
        "analyze_frame",
        lambda path: "Antigravity 看見畫面中的 VS Code 與三個步驟",
    )

    def fail_if_ollama_used(*args, **kwargs):
        raise AssertionError("Ollama should not be used on Antigravity success")

    monkeypatch.setattr(analyzer, "_analyze_frame_with_ollama_sync", fail_if_ollama_used)

    result = analyzer._analyze_frame_sync(frame, 1, 10, 100.0)

    assert result.timestamp == 10.0
    assert "Antigravity" in result.description


def test_video_frame_falls_back_to_ollama_on_antigravity_error(monkeypatch, tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"fake")
    monkeypatch.setattr(visual_module.settings, "visual_analyzer_backend", "antigravity", raising=False)

    analyzer = VideoVisualAnalyzer()

    def agy_fails(path: Path) -> str:
        raise AntigravityAnalysisError("timeout")

    monkeypatch.setattr(analyzer.antigravity_analyzer, "analyze_frame", agy_fails)
    monkeypatch.setattr(
        analyzer,
        "_analyze_frame_with_ollama_sync",
        lambda image_path, frame_index, total_frames, duration: visual_module.FrameDescription(
            timestamp=10.0,
            description="Ollama fallback 成功",
        ),
    )

    result = analyzer._analyze_frame_sync(frame, 1, 10, 100.0)

    assert result.description == "Ollama fallback 成功"


@pytest.mark.asyncio
async def test_native_video_success_bypasses_frame_extraction(monkeypatch, tmp_path):
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(visual_module.settings, "visual_analyzer_backend", "antigravity")

    analyzer = VideoVisualAnalyzer()
    monkeypatch.setattr(
        analyzer.antigravity_analyzer,
        "analyze_video",
        lambda path: "Antigravity 直接看完整影片：畫面顯示 SQL、Python、LangChain",
    )

    def fail_if_frames_used(*args, **kwargs):
        raise AssertionError("FFmpeg frame extraction must be bypassed on native success")

    monkeypatch.setattr(analyzer, "_extract_frames", fail_if_frames_used)

    result = await analyzer.analyze(video)

    assert result.success is True
    assert "LangChain" in result.overall_visual_summary
    assert len(result.frame_descriptions) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [AntigravityAnalysisError("timeout"), OSError("resource unavailable")],
)
async def test_native_video_error_falls_back_to_ollama_frames(monkeypatch, tmp_path, error):
    video = tmp_path / "reel.mp4"
    frame = tmp_path / "frame_001.jpg"
    video.write_bytes(b"fake")
    frame.write_bytes(b"fake")
    monkeypatch.setattr(visual_module.settings, "visual_analyzer_backend", "antigravity")

    analyzer = VideoVisualAnalyzer()

    def agy_video_fails(path: Path) -> str:
        raise error

    monkeypatch.setattr(analyzer.antigravity_analyzer, "analyze_video", agy_video_fails)
    monkeypatch.setattr(analyzer.antigravity_analyzer, "analyze_frame", lambda path: (_ for _ in ()).throw(AssertionError("fallback must not call agy per-frame")))
    monkeypatch.setattr(analyzer, "_get_video_duration", lambda path: 10.0)
    monkeypatch.setattr(analyzer, "_extract_frames", lambda path: [frame])
    monkeypatch.setattr(analyzer, "_cleanup_frames", lambda frames: None)
    monkeypatch.setattr(
        analyzer,
        "_analyze_frame_with_ollama_sync",
        lambda image_path, frame_index, total_frames, duration: visual_module.FrameDescription(
            timestamp=0.0,
            description="Ollama frame fallback",
        ),
    )

    result = await analyzer.analyze(video)

    assert result.success is True
    assert result.overall_visual_summary == "[0秒] Ollama frame fallback"


def test_video_frame_uses_ollama_by_default(monkeypatch, tmp_path):
    frame = tmp_path / "frame.jpg"
    frame.write_bytes(b"fake")
    monkeypatch.setattr(visual_module.settings, "visual_analyzer_backend", "ollama", raising=False)

    analyzer = VideoVisualAnalyzer()

    def fail_if_agy_used(path: Path) -> str:
        raise AssertionError("Antigravity should not be used for ollama backend")

    monkeypatch.setattr(analyzer.antigravity_analyzer, "analyze_frame", fail_if_agy_used)
    monkeypatch.setattr(
        analyzer,
        "_analyze_frame_with_ollama_sync",
        lambda image_path, frame_index, total_frames, duration: visual_module.FrameDescription(
            timestamp=20.0,
            description="Ollama default",
        ),
    )

    result = analyzer._analyze_frame_sync(frame, 2, 10, 100.0)

    assert result.description == "Ollama default"
