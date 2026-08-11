"""F21: Antigravity CLI visual analyzer backend tests."""

import subprocess
from pathlib import Path

import pytest

from app.services.antigravity_visual_analyzer import (
    AntigravityAnalysisError,
    AntigravityCLIFrameAnalyzer,
)


def test_analyze_frame_invokes_restricted_custom_agent(monkeypatch, tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg")
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(args, 0, stdout="畫面顯示一個終端機視窗", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    analyzer = AntigravityCLIFrameAnalyzer(
        cli_path="agy",
        agent_name="reels-vision",
        model="gemini-3.6-flash-high",
        timeout_seconds=45,
    )

    result = analyzer.analyze_frame(image_path)

    assert result == "畫面顯示一個終端機視窗"
    args = captured["args"]
    assert args[0] == "agy"
    assert args[1] == "-p"
    assert str(image_path.resolve()) in args[2]
    assert args[args.index("--agent") + 1] == "reels-vision"
    assert args[args.index("--add-dir") + 1] == str(image_path.resolve().parent)
    assert args[args.index("--model") + 1] == "gemini-3.6-flash-high"
    assert args[args.index("--mode") + 1] == "plan"
    assert args[args.index("--print-timeout") + 1] == "45s"
    assert "--dangerously-skip-permissions" in args
    assert "--sandbox" in args
    assert captured["kwargs"]["timeout"] == 50
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert captured["kwargs"]["errors"] == "replace"


def test_analyze_video_invokes_native_media_with_workspace(monkeypatch, tmp_path):
    video_path = tmp_path / "reel.mp4"
    video_path.write_bytes(b"fake-mp4")
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        granted_dir = Path(args[args.index("--add-dir") + 1])
        captured["granted_files"] = [path.name for path in granted_dir.iterdir()]
        return subprocess.CompletedProcess(
            args,
            0,
            stdout="影片展示資料職位技能表與 SQL、Python、LangChain 等工具",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    analyzer = AntigravityCLIFrameAnalyzer(timeout_seconds=120)

    result = analyzer.analyze_video(video_path)

    assert "LangChain" in result
    args = captured["args"]
    granted_dir = Path(args[args.index("--add-dir") + 1])
    assert granted_dir.parent == video_path.resolve().parent
    assert granted_dir != video_path.resolve().parent
    assert str(granted_dir / video_path.name) in args[2]
    assert captured["granted_files"] == [video_path.name]
    assert not granted_dir.exists()
    assert args[args.index("--print-timeout") + 1] == "120s"


def test_analyze_frame_timeout_is_wrapped(monkeypatch, tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg")

    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    analyzer = AntigravityCLIFrameAnalyzer(timeout_seconds=10)

    with pytest.raises(AntigravityAnalysisError, match="timeout"):
        analyzer.analyze_frame(image_path)


def test_analyze_frame_missing_cli_is_wrapped(monkeypatch, tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg")

    def fake_run(args, **kwargs):
        raise FileNotFoundError(args[0])

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(AntigravityAnalysisError, match="CLI not found"):
        AntigravityCLIFrameAnalyzer().analyze_frame(image_path)


def test_analyze_frame_nonzero_exit_is_wrapped(monkeypatch, tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg")

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="auth failed")

    monkeypatch.setattr(subprocess, "run", fake_run)
    analyzer = AntigravityCLIFrameAnalyzer()

    with pytest.raises(AntigravityAnalysisError, match="auth failed"):
        analyzer.analyze_frame(image_path)


def test_analyze_frame_empty_output_is_wrapped(monkeypatch, tmp_path):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg")

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="   ", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    analyzer = AntigravityCLIFrameAnalyzer()

    with pytest.raises(AntigravityAnalysisError, match="empty output"):
        analyzer.analyze_frame(image_path)


def test_analyze_frame_rejects_missing_file():
    analyzer = AntigravityCLIFrameAnalyzer()

    with pytest.raises(AntigravityAnalysisError, match="not found"):
        analyzer.analyze_frame(Path("missing.jpg"))
