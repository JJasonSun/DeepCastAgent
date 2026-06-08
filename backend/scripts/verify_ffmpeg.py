import os  # noqa: D100
import shutil
from pathlib import Path

from pydub import AudioSegment

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

"""
DeepCast 项目使用 pydub 库将多个 TTS 生成的音频片段（MP3）合成为最终的播客文件。
pydub 底层依赖 ffmpeg 进行音频格式转换和处理（特别是 MP3 导出）。
因此，必须确保系统已安装 ffmpeg 且 Python 环境能正确找到其路径。
此脚本用于验证 ffmpeg 是否配置正确且能被 pydub 调用。
"""

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = BACKEND_ROOT / ".env"


def _read_ffmpeg_path_from_env_file(env_path: Path) -> str | None:
    if not env_path.exists():
        return None

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        if key.strip() == "FFMPEG_PATH":
            return value.strip().strip("\"'")

    return None


if load_dotenv:
    load_dotenv(ENV_PATH)
elif "FFMPEG_PATH" not in os.environ:
    env_ffmpeg_path = _read_ffmpeg_path_from_env_file(ENV_PATH)
    if env_ffmpeg_path:
        os.environ["FFMPEG_PATH"] = env_ffmpeg_path

# 优先使用环境变量配置；未配置时回退到系统 PATH。
ffmpeg_path = os.getenv("FFMPEG_PATH") or shutil.which("ffmpeg")
if ffmpeg_path:
    AudioSegment.converter = ffmpeg_path


def test_ffmpeg():
    print(f"Testing ffmpeg at: {ffmpeg_path}")
    
    # Check if file exists
    if not ffmpeg_path:
        print("❌ Failed: FFMPEG_PATH is not set and ffmpeg was not found on PATH.")
        return
    if not os.path.exists(ffmpeg_path):
        print(f"❌ Warning: ffmpeg executable not found at {ffmpeg_path}")
    else:
        print("✅ ffmpeg executable found.")
    
    try:
        # 创建 1 秒的静音片段
        print("Creating silent audio segment...")
        silence = AudioSegment.silent(duration=1000)
        
        output_file = "test_ffmpeg_output.mp3"
        print(f"Exporting to {output_file}...")
        
        # 导出需要 ffmpeg
        silence.export(output_file, format="mp3")
        
        if os.path.exists(output_file):
            print("✅ Success! ffmpeg is working correctly.")
            print(f"Output file size: {os.path.getsize(output_file)} bytes")
            # 清理文件
            os.remove(output_file)
        else:
            print("❌ Failed: Output file was not created.")
            
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    test_ffmpeg()
