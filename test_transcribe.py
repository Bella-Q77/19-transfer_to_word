"""
无 GUI 的转录测试脚本
直接对指定文件进行转录，验证完整流程
"""
import sys
import os
import time

# 设置 HuggingFace 镜像（国内加速）
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from audio_to_text import (
    extract_audio_from_video,
    transcribe_with_faster_whisper,
    assign_speakers,
    format_output,
    open_file,
    FFMPEG_PATH,
    VIDEO_FORMATS,
)
from datetime import datetime


def main():
    input_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "第1节 位运算、算法是什么、简单排序.mp4",
    )

    if not os.path.isfile(input_file):
        print(f"错误：文件不存在 - {input_file}")
        sys.exit(1)

    print(f"源文件: {os.path.basename(input_file)}")
    print(f"文件大小: {os.path.getsize(input_file) / 1024 / 1024:.1f} MB")
    print(f"FFMPEG: {FFMPEG_PATH}")
    print()

    start_time = time.time()

    # 提取音频
    ext = os.path.splitext(input_file)[1].lower()
    audio_path = input_file
    temp_audio = None

    if ext in VIDEO_FORMATS:
        print("[1/4] 正在从视频中提取音频...")
        temp_audio = os.path.join(os.path.dirname(input_file), "_temp_audio_test.wav")
        audio_path = extract_audio_from_video(input_file, temp_audio)
        print(f"      音频提取完成，大小: {os.path.getsize(temp_audio) / 1024 / 1024:.1f} MB")
    else:
        print("[1/4] 音频文件，跳过提取步骤")

    # 转录
    print("[2/4] 正在转录（使用 small 模型，首次需下载）...")

    def progress(msg, val):
        print(f"      {msg} [{val}%]")

    result = transcribe_with_faster_whisper(audio_path, model_name="tiny", language="zh", progress_callback=progress)
    segments = result["segments"]
    print(f"      转录完成，共 {len(segments)} 个片段")

    # 说话人分离
    print("[3/4] 正在进行说话人分离...")
    segments = assign_speakers(segments)

    # 格式化输出
    print("[4/4] 正在生成文档...")
    duration = segments[-1]["end"] if segments else 0
    file_info = {
        "filename": os.path.basename(input_file),
        "transcribe_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "language": result.get("language", "zh"),
        "duration": duration,
        "model": "tiny",
    }

    output_text = format_output(segments, file_info)

    # 保存
    base_name = os.path.splitext(os.path.basename(input_file))[0]
    output_filename = f"{base_name}_转录_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    output_path = os.path.join(os.path.dirname(input_file), output_filename)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_text)

    # 清理临时文件
    if temp_audio and os.path.exists(temp_audio):
        os.remove(temp_audio)

    elapsed = time.time() - start_time
    print()
    print(f"转录完成！耗时: {elapsed:.1f} 秒")
    print(f"输出文件: {output_path}")
    print()

    # 打开预览
    print("正在打开文件预览...")
    open_file(output_path)


if __name__ == "__main__":
    main()
