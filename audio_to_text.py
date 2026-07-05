"""
音视频对话转文字工具
====================
功能：将音频/视频文件中的对话转录为文字，自动识别不同说话人，
      输出排版清晰的文本文档并自动打开预览。

支持格式：mp3, wav, flac, ogg, m4a, wma, aac, mp4, avi, mkv, mov, wmv, flv, webm 等

依赖安装：
    pip install openai-whisper faster-whisper pydub tkinterdnd2
    另需安装 ffmpeg 并添加到系统 PATH
"""

import os
import sys
import time
import threading
import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime, timedelta
from pathlib import Path

# 支持的文件格式
AUDIO_FORMATS = (".mp3", ".wav", ".flac", ".ogg", ".m4a", ".wma", ".aac", ".opus", ".amr")
VIDEO_FORMATS = (".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".ts", ".mpeg")
ALL_FORMATS = AUDIO_FORMATS + VIDEO_FORMATS

# ffmpeg 路径自动检测
FFMPEG_PATH = "ffmpeg"

def _find_ffmpeg():
    """自动查找系统中的 ffmpeg"""
    global FFMPEG_PATH
    # 先尝试 PATH 中的 ffmpeg
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return True
    except FileNotFoundError:
        pass

    # 在常见位置搜索
    search_paths = [
        r"C:\Program Files\EVCapture\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
        os.path.expanduser(r"~\ffmpeg\bin\ffmpeg.exe"),
    ]
    for path in search_paths:
        if os.path.isfile(path):
            FFMPEG_PATH = path
            return True
    return False

_find_ffmpeg()


def check_dependencies():
    """检查依赖是否已安装"""
    missing = []

    # 检查 ffmpeg
    try:
        subprocess.run(
            [FFMPEG_PATH, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except FileNotFoundError:
        missing.append("ffmpeg (请从 https://ffmpeg.org/download.html 下载并添加到 PATH)")

    # 检查 whisper
    try:
        import whisper  # noqa: F401
    except ImportError:
        try:
            from faster_whisper import WhisperModel  # noqa: F401
        except ImportError:
            missing.append("openai-whisper 或 faster-whisper (pip install openai-whisper 或 pip install faster-whisper)")

    return missing


def format_timestamp(seconds):
    """将秒数格式化为 HH:MM:SS"""
    td = timedelta(seconds=int(seconds))
    hours = td.seconds // 3600
    minutes = (td.seconds % 3600) // 60
    secs = td.seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def extract_audio_from_video(video_path, output_path):
    """从视频文件中提取音频"""
    cmd = [
        FFMPEG_PATH, "-i", video_path,
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        "-y", output_path,
    ]
    process = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    if process.returncode != 0:
        raise RuntimeError(f"音频提取失败: {process.stderr.decode('utf-8', errors='ignore')}")
    return output_path


def transcribe_with_whisper(audio_path, model_name="medium", language=None, progress_callback=None):
    """使用 OpenAI Whisper 进行转录"""
    import whisper

    # 使用国内镜像加速模型下载
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    if progress_callback:
        progress_callback("正在加载 Whisper 模型...", 10)

    model = whisper.load_model(model_name)

    if progress_callback:
        progress_callback("正在转录音频（这可能需要几分钟）...", 30)

    options = {"verbose": False}
    if language:
        options["language"] = language

    result = model.transcribe(audio_path, **options)

    if progress_callback:
        progress_callback("转录完成，正在处理结果...", 80)

    return result


def transcribe_with_faster_whisper(audio_path, model_name="medium", language=None, progress_callback=None):
    """使用 faster-whisper 进行转录（速度更快）"""
    from faster_whisper import WhisperModel

    # 使用国内镜像加速模型下载
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    if progress_callback:
        progress_callback("正在加载 Faster-Whisper 模型...", 10)

    model = WhisperModel(model_name, device="auto", compute_type="auto")

    if progress_callback:
        progress_callback("正在转录音频（这可能需要几分钟）...", 30)

    kwargs = {"beam_size": 5, "vad_filter": True}
    if language:
        kwargs["language"] = language

    segments, info = model.transcribe(audio_path, **kwargs)

    if progress_callback:
        progress_callback(f"检测到语言: {info.language} (置信度: {info.language_probability:.1%})", 50)

    result_segments = []
    for segment in segments:
        result_segments.append({
            "start": segment.start,
            "end": segment.end,
            "text": segment.text.strip(),
        })

    if progress_callback:
        progress_callback("转录完成，正在处理结果...", 80)

    return {
        "segments": result_segments,
        "language": info.language,
    }


def assign_speakers(segments, min_pause=2.0):
    """
    基于停顿时间的简易说话人分离。
    当两段话之间的停顿超过阈值时，判定为说话人切换。
    """
    if not segments:
        return segments

    current_speaker = 1
    segments[0]["speaker"] = f"说话人 {current_speaker}"

    for i in range(1, len(segments)):
        pause = segments[i]["start"] - segments[i - 1]["end"]
        if pause >= min_pause:
            current_speaker = 1 if current_speaker == 2 else 2
        segments[i]["speaker"] = f"说话人 {current_speaker}"

    return segments


def format_output(segments, file_info):
    """格式化输出文本"""
    lines = []
    separator = "=" * 60

    # 文件头信息
    lines.append(separator)
    lines.append("              音视频对话转录文档")
    lines.append(separator)
    lines.append("")
    lines.append(f"  源文件：{file_info['filename']}")
    lines.append(f"  转录时间：{file_info['transcribe_time']}")
    if file_info.get("language"):
        lang_map = {"zh": "中文", "en": "英文", "ja": "日语", "ko": "韩语", "fr": "法语", "de": "德语"}
        lang_display = lang_map.get(file_info["language"], file_info["language"])
        lines.append(f"  识别语言：{lang_display}")
    if file_info.get("duration"):
        lines.append(f"  音频时长：{format_timestamp(file_info['duration'])}")
    lines.append(f"  模型：{file_info.get('model', 'medium')}")
    lines.append("")
    lines.append(separator)
    lines.append("")
    lines.append("【对话内容】")
    lines.append("")

    # 对话内容
    current_speaker = None
    for seg in segments:
        speaker = seg.get("speaker", "未知")
        timestamp = format_timestamp(seg["start"])

        if speaker != current_speaker:
            if current_speaker is not None:
                lines.append("")
            lines.append(f"┌─ {speaker} [{timestamp}]")
            lines.append(f"│")
            current_speaker = speaker

        text = seg["text"]
        lines.append(f"│  {text}")

    lines.append("")
    lines.append(separator)
    lines.append("")
    lines.append(f"[文档结束 - 共 {len(segments)} 段对话]")
    lines.append("")

    return "\n".join(lines)


def open_file(filepath):
    """用系统默认程序打开文件"""
    if sys.platform == "win32":
        os.startfile(filepath)
    elif sys.platform == "darwin":
        subprocess.run(["open", filepath])
    else:
        subprocess.run(["xdg-open", filepath])


class TranscriberApp:
    """音视频转文字工具 GUI"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("音视频对话转文字工具")
        self.root.geometry("700x580")
        self.root.resizable(True, True)
        self.root.configure(bg="#f0f0f0")

        self.selected_file = tk.StringVar()
        self.model_var = tk.StringVar(value="medium")
        self.language_var = tk.StringVar(value="auto")
        self.output_path = None
        self.is_processing = False

        self._build_ui()

    def _build_ui(self):
        """构建界面"""
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("TButton", font=("Microsoft YaHei UI", 10), padding=6)
        style.configure("TLabel", font=("Microsoft YaHei UI", 10))
        style.configure("Header.TLabel", font=("Microsoft YaHei UI", 11, "bold"))

        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 标题
        title_label = ttk.Label(main_frame, text="音视频对话转文字工具", style="Title.TLabel")
        title_label.pack(pady=(0, 15))

        # 文件选择区域
        file_frame = ttk.LabelFrame(main_frame, text="文件选择", padding=10)
        file_frame.pack(fill=tk.X, pady=(0, 10))

        file_inner = ttk.Frame(file_frame)
        file_inner.pack(fill=tk.X)

        self.file_entry = ttk.Entry(file_inner, textvariable=self.selected_file, state="readonly")
        self.file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        browse_btn = ttk.Button(file_inner, text="浏览文件", command=self._browse_file)
        browse_btn.pack(side=tk.RIGHT)

        # 设置区域
        settings_frame = ttk.LabelFrame(main_frame, text="转录设置", padding=10)
        settings_frame.pack(fill=tk.X, pady=(0, 10))

        settings_grid = ttk.Frame(settings_frame)
        settings_grid.pack(fill=tk.X)

        # 模型选择
        ttk.Label(settings_grid, text="模型大小:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        model_combo = ttk.Combobox(
            settings_grid, textvariable=self.model_var,
            values=["tiny", "base", "small", "medium", "large"],
            state="readonly", width=15,
        )
        model_combo.grid(row=0, column=1, sticky=tk.W)
        ttk.Label(
            settings_grid, text="(tiny最快/large最准确，首次使用会下载模型)",
            foreground="gray",
        ).grid(row=0, column=2, sticky=tk.W, padx=(10, 0))

        # 语言选择
        ttk.Label(settings_grid, text="音频语言:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(5, 0))
        lang_combo = ttk.Combobox(
            settings_grid, textvariable=self.language_var,
            values=["auto", "zh", "en", "ja", "ko", "fr", "de"],
            state="readonly", width=15,
        )
        lang_combo.grid(row=1, column=1, sticky=tk.W, pady=(5, 0))
        ttk.Label(
            settings_grid, text="(auto=自动检测, zh=中文, en=英文)",
            foreground="gray",
        ).grid(row=1, column=2, sticky=tk.W, padx=(10, 0), pady=(5, 0))

        # 操作按钮
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.start_btn = ttk.Button(btn_frame, text="开始转录", command=self._start_transcription)
        self.start_btn.pack(side=tk.LEFT)

        self.open_btn = ttk.Button(btn_frame, text="打开结果文件", command=self._open_result, state=tk.DISABLED)
        self.open_btn.pack(side=tk.LEFT, padx=(10, 0))

        # 进度条
        self.progress = ttk.Progressbar(main_frame, mode="determinate", length=400)
        self.progress.pack(fill=tk.X, pady=(0, 5))

        self.status_var = tk.StringVar(value="就绪 - 请选择音频或视频文件")
        status_label = ttk.Label(main_frame, textvariable=self.status_var, foreground="blue")
        status_label.pack(anchor=tk.W, pady=(0, 10))

        # 日志区域
        log_frame = ttk.LabelFrame(main_frame, text="处理日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = scrolledtext.ScrolledText(log_frame, height=10, font=("Consolas", 9), state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def _log(self, message):
        """向日志区域添加信息"""
        self.log_text.config(state=tk.NORMAL)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _browse_file(self):
        """浏览选择文件"""
        filetypes = [
            ("音视频文件", " ".join(f"*{ext}" for ext in ALL_FORMATS)),
            ("音频文件", " ".join(f"*{ext}" for ext in AUDIO_FORMATS)),
            ("视频文件", " ".join(f"*{ext}" for ext in VIDEO_FORMATS)),
            ("所有文件", "*.*"),
        ]
        filepath = filedialog.askopenfilename(title="选择音频或视频文件", filetypes=filetypes)
        if filepath:
            self.selected_file.set(filepath)
            self._log(f"已选择文件: {os.path.basename(filepath)}")

    def _update_progress(self, message, value):
        """更新进度条和状态"""
        self.progress["value"] = value
        self.status_var.set(message)
        self._log(message)
        self.root.update_idletasks()

    def _start_transcription(self):
        """开始转录处理"""
        filepath = self.selected_file.get()
        if not filepath:
            messagebox.showwarning("提示", "请先选择一个音频或视频文件！")
            return

        if not os.path.isfile(filepath):
            messagebox.showerror("错误", "所选文件不存在！")
            return

        ext = os.path.splitext(filepath)[1].lower()
        if ext not in ALL_FORMATS:
            messagebox.showwarning("提示", f"不支持的文件格式: {ext}")
            return

        # 检查依赖
        missing = check_dependencies()
        if missing:
            msg = "缺少以下依赖，请先安装：\n\n" + "\n".join(f"• {m}" for m in missing)
            messagebox.showerror("依赖缺失", msg)
            return

        self.is_processing = True
        self.start_btn.config(state=tk.DISABLED)
        self.open_btn.config(state=tk.DISABLED)

        thread = threading.Thread(target=self._do_transcription, args=(filepath,), daemon=True)
        thread.start()

    def _do_transcription(self, filepath):
        """在后台线程中执行转录"""
        try:
            start_time = time.time()
            ext = os.path.splitext(filepath)[1].lower()
            audio_path = filepath
            temp_audio = None

            # 如果是视频文件，先提取音频
            if ext in VIDEO_FORMATS:
                self.root.after(0, self._update_progress, "正在从视频中提取音频...", 5)
                temp_audio = os.path.join(os.path.dirname(filepath), "_temp_audio.wav")
                audio_path = extract_audio_from_video(filepath, temp_audio)
                self.root.after(0, self._log, "音频提取完成")

            # 选择转录引擎
            language = self.language_var.get()
            if language == "auto":
                language = None
            model_name = self.model_var.get()

            def progress_cb(msg, val):
                self.root.after(0, self._update_progress, msg, val)

            # 优先使用 faster-whisper
            try:
                from faster_whisper import WhisperModel  # noqa: F401
                self.root.after(0, self._log, "使用 faster-whisper 引擎")
                result = transcribe_with_faster_whisper(audio_path, model_name, language, progress_cb)
                segments = result["segments"]
                detected_lang = result.get("language")
            except ImportError:
                self.root.after(0, self._log, "使用 openai-whisper 引擎")
                result = transcribe_with_whisper(audio_path, model_name, language, progress_cb)
                segments = [
                    {"start": seg["start"], "end": seg["end"], "text": seg["text"].strip()}
                    for seg in result["segments"]
                ]
                detected_lang = result.get("language")

            # 说话人分离
            self.root.after(0, self._update_progress, "正在进行说话人分离...", 85)
            segments = assign_speakers(segments)

            # 格式化输出
            self.root.after(0, self._update_progress, "正在生成文档...", 90)

            duration = segments[-1]["end"] if segments else 0
            file_info = {
                "filename": os.path.basename(filepath),
                "transcribe_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "language": detected_lang,
                "duration": duration,
                "model": model_name,
            }

            output_text = format_output(segments, file_info)

            # 保存文件
            output_dir = os.path.dirname(filepath)
            base_name = os.path.splitext(os.path.basename(filepath))[0]
            output_filename = f"{base_name}_转录_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            self.output_path = os.path.join(output_dir, output_filename)

            with open(self.output_path, "w", encoding="utf-8") as f:
                f.write(output_text)

            # 清理临时文件
            if temp_audio and os.path.exists(temp_audio):
                os.remove(temp_audio)

            elapsed = time.time() - start_time
            self.root.after(0, self._update_progress, f"转录完成！耗时 {elapsed:.1f} 秒", 100)
            self.root.after(0, self._log, f"输出文件: {self.output_path}")
            self.root.after(0, self._on_complete)

        except Exception as e:
            self.root.after(0, self._on_error, str(e))

    def _on_complete(self):
        """转录完成后的处理"""
        self.is_processing = False
        self.start_btn.config(state=tk.NORMAL)
        self.open_btn.config(state=tk.NORMAL)

        if messagebox.askyesno("转录完成", "转录已完成！是否立即打开结果文件？"):
            self._open_result()

    def _on_error(self, error_msg):
        """处理错误"""
        self.is_processing = False
        self.start_btn.config(state=tk.NORMAL)
        self.progress["value"] = 0
        self.status_var.set("转录失败")
        self._log(f"错误: {error_msg}")
        messagebox.showerror("转录失败", f"处理过程中出现错误:\n\n{error_msg}")

    def _open_result(self):
        """打开结果文件"""
        if self.output_path and os.path.isfile(self.output_path):
            open_file(self.output_path)
        else:
            messagebox.showinfo("提示", "没有可打开的结果文件")

    def run(self):
        """运行应用"""
        self.root.mainloop()


if __name__ == "__main__":
    app = TranscriberApp()
    app.run()
