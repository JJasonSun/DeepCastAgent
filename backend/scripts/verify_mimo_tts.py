"""验证 MiMo TTS API 连通性和音色效果。"""

import base64
import os
import sys

from dotenv import load_dotenv

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

# Load env
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))


def test_mimo_tts():
    from openai import OpenAI

    api_key = os.getenv("TTS_API_KEY")
    base_url = os.getenv("TTS_BASE_URL", "https://api.xiaomimimo.com/v1")
    model = os.getenv("TTS_MODEL", "mimo-v2.5-tts")

    print("Testing MiMo TTS API...")
    print(f"Base URL: {base_url}")
    print(f"Model: {model}")
    print(f"API Key: {api_key[:8]}..." if api_key else "API Key: None")

    if not api_key:
        print("❌ Error: TTS_API_KEY not found in environment variables")
        return

    client = OpenAI(api_key=api_key, base_url=base_url)

    # 测试音色列表：苏打（男声）和 冰糖（女声）
    voices = [
        {"name": "苏打", "style": "用温暖、活泼、略带幽默的语气说话", "text": "大家好，欢迎收听今天的播客节目！今天我们来聊聊一个非常有趣的话题。"},
        {"name": "冰糖", "style": "用专业、清晰、沉稳的语气说话", "text": "好的，让我来为大家详细介绍一下这个领域的最新进展。"},
    ]

    for i, voice_config in enumerate(voices):
        print(f"\n--- 测试 {i+1}: 音色 '{voice_config['name']}' ---")
        try:
            messages = [
                {"role": "user", "content": voice_config["style"]},
                {"role": "assistant", "content": voice_config["text"]},
            ]

            completion = client.chat.completions.create(
                model=model,
                messages=messages,
                audio={"format": "wav", "voice": voice_config["name"]},
                timeout=60,
            )

            audio_data = completion.choices[0].message.audio
            if not audio_data or not audio_data.data:
                print(f"❌ 音色 '{voice_config['name']}': 返回空音频数据")
                continue

            audio_bytes = base64.b64decode(audio_data.data)
            output_file = f"test_mimo_{voice_config['name']}.wav"
            with open(output_file, "wb") as f:
                f.write(audio_bytes)

            print(f"✅ 音色 '{voice_config['name']}': 音频已保存到 {output_file}")
            print(f"   文件大小: {len(audio_bytes)} bytes")

        except Exception as e:
            print(f"❌ 音色 '{voice_config['name']}': {e}")


if __name__ == "__main__":
    test_mimo_tts()
