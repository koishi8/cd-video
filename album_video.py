"""Album Video: standard-library desktop application, FFmpeg does all media work."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

CREATE_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


class Cancelled(Exception):
    pass


class Runner:
    def __init__(self):
        self.cancel = threading.Event()

    def run(self, args, stdout=None):
        if self.cancel.is_set():
            raise Cancelled('已取消')
        # A file for stderr avoids pipe deadlocks during long encodes.
        with tempfile.TemporaryFile() as errors:
            p = subprocess.Popen([str(a) for a in args], stdout=stdout or subprocess.PIPE,
                                 stderr=errors, creationflags=CREATE_FLAGS)
            result = b''
            while True:
                try:
                    result, _ = p.communicate(timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    if self.cancel.is_set():
                        p.kill()
                        p.communicate()
                        raise Cancelled('已取消')
            if p.returncode:
                errors.seek(0)
                detail = errors.read().decode('utf-8', errors='replace')
                raise RuntimeError(detail[-6000:] or '外部程序运行失败')
            return result or b''


def find_tools(path=''):
    candidates = []
    if path:
        p = Path(path).expanduser()
        candidates.append(p / 'ffmpeg.exe' if p.is_dir() else p)
    else:
        base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
        candidates += [base / 'ffmpeg.exe', base / 'ffmpeg' / 'bin' / 'ffmpeg.exe']
        found = shutil.which('ffmpeg')
        if found:
            candidates.append(Path(found))
    for exe in candidates:
        probe = exe.with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
        if exe.is_file() and probe.is_file():
            r = Runner()
            r.run([exe, '-version'])
            r.run([probe, '-version'])
            return exe.resolve(), probe.resolve()
    raise ValueError('没有找到 FFmpeg 和 FFprobe。请选择同一套工具中的 ffmpeg.exe，旁边需有 ffprobe.exe。')


@dataclass
class Track:
    path: Path
    title: str
    duration: Fraction
    rate: int
    channels: int
    bits: int
    floating: bool
    number: int | None
    disc: int | None


def tag_number(value):
    m = re.match(r'^\s*(\d+)(?:\s*/\s*\d+)?\s*$', str(value or ''))
    return int(m[1]) if m and int(m[1]) > 0 else None


def inspect_track(path, probe, runner):
    data = json.loads(runner.run([probe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path]))
    stream = next((s for s in data['streams'] if s['codec_type'] == 'audio'), None)
    if not stream:
        raise ValueError(f'没有音频流：{path.name}')
    tags = {k.lower(): v for source in (data.get('format', {}), stream)
            for k, v in source.get('tags', {}).items()}
    if stream.get('duration_ts') is not None and stream.get('time_base'):
        duration = Fraction(stream['duration_ts']) * Fraction(stream['time_base'])
    else:
        duration = Fraction(stream.get('duration') or data['format'].get('duration', '0'))
    if duration <= 0:
        raise ValueError(f'无法读取时长：{path.name}')
    fmt = stream.get('sample_fmt', '')
    bits = int(stream.get('bits_per_raw_sample') or stream.get('bits_per_sample') or 0)
    if not bits:
        bits = 16 if fmt.startswith('s16') else 32
    return Track(path, tags.get('title') or path.stem, duration,
                 int(stream['sample_rate']), int(stream['channels']), bits,
                 fmt.startswith(('flt', 'dbl')), tag_number(tags.get('track') or tags.get('tracknumber')),
                 tag_number(tags.get('disc') or tags.get('discnumber')))


def scan(folder, probe, runner, log=lambda _: None):
    paths = sorted((p for p in Path(folder).iterdir() if p.suffix.lower() in ('.flac', '.wav') and p.is_file()),
                   key=lambda p: p.name.casefold())
    if not paths:
        raise ValueError('所选文件夹中没有 FLAC 或 WAV 音源（只读取当前文件夹）。')
    tracks = []
    for i, path in enumerate(paths, 1):
        log(f'读取音源 {i}/{len(paths)}：{path.name}')
        tracks.append(inspect_track(path, probe, runner))
    return tracks


def automatic_order(tracks):
    # Missing disc tags are safe for a single disc; ambiguous duplicate track numbers are not.
    if any(t.number is None for t in tracks):
        return None
    if any(t.disc is not None for t in tracks) and any(t.disc is None for t in tracks):
        return None
    keys = [(t.disc or 1, t.number) for t in tracks]
    if len(set(keys)) != len(keys):
        return None
    return sorted(tracks, key=lambda t: (t.disc or 1, t.number))


def manual_order(tracks, values):
    try:
        nums = [int(v) for v in values]
    except ValueError:
        raise ValueError('顺序必须填写整数。') from None
    if len(nums) != len(tracks) or sorted(nums) != list(range(1, len(tracks) + 1)):
        raise ValueError(f'请完整填写 1–{len(tracks)}，每个数字只能出现一次。')
    return [t for _, t in sorted(zip(nums, tracks), key=lambda pair: pair[0])]


def split_album(tracks):
    if sum((t.duration for t in tracks), Fraction()) > 3600 and len(tracks) > 1:
        mid = (len(tracks) + 1) // 2
        return [tracks[:mid], tracks[mid:]]
    return [tracks]


def clock(seconds):
    n = math.floor(seconds)
    return f'{n // 3600:02d}:{n // 60 % 60:02d}:{n % 60:02d}'


def safe_name(name):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .') or '专辑'


def render(tracks, cover, output, ffmpeg, runner, log=lambda _: None):
    if len({(t.rate, t.channels) for t in tracks}) != 1:
        raise ValueError('音源的采样率或声道数不一致。为保留无损音质，程序不会自动重采样；请使用规格一致的音源。')
    parts = split_album(tracks)
    if len(tracks) == 1 and tracks[0].duration > 3600:
        raise ValueError('单首音源超过一小时，无法按歌曲分成两半。请先分轨。')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    stem = safe_name(tracks[0].path.parent.name)
    # Reserve a unique result directory; never overwrite previous work.
    dest = output / stem
    n = 2
    while True:
        try:
            dest.mkdir()
            break
        except FileExistsError:
            dest = output / f'{stem} ({n})'
            n += 1
    complete = False
    try:
        with tempfile.TemporaryDirectory(prefix='.album-work-', dir=dest) as work:
            work = Path(work)
            log('处理封面：等比缩放到宽 1080，垂直居中裁剪；不足 1080 高时上下补黑。')
            still = work / 'still.mkv'
            runner.run([ffmpeg, '-hide_banner', '-v', 'error', '-y', '-loop', '1', '-i', cover,
                        '-vf', 'scale=1080:-1:flags=lanczos,pad=1080:max(1080\,ih):(ow-iw)/2:(oh-ih)/2,crop=1080:1080,setsar=1',
                        '-r', '30', '-t', '1', '-an', '-c:v', 'libx264', '-preset', 'veryfast',
                        '-tune', 'stillimage', '-crf', '18', '-pix_fmt', 'yuv420p', '-g', '30', '-bf', '0', still])
            rate, channels = tracks[0].rate, tracks[0].channels
            floating = any(t.floating for t in tracks)
            bits = max(t.bits for t in tracks)
            raw_fmt, raw_codec, width = ('f64le', 'pcm_f64le', 8) if floating else (
                ('s16le', 'pcm_s16le', 2) if bits <= 16 else ('s32le', 'pcm_s32le', 4))
            # FLAC carries 16/24-bit integer material exactly. 32-bit and float use lossless PCM.
            audio_codec = raw_codec if floating or bits > 24 else 'flac'
            text_lines = [stem, '时间格式 HH:MM:SS；每个时间点均向下取整；结束时间为下一首的起点。', '']
            global_index = 0
            for part_no, part in enumerate(parts, 1):
                raw = work / 'audio.raw'
                offsets = []
                with raw.open('wb') as sink:
                    for track in part:
                        log(f'第 {part_no}/{len(parts)} 部分：读取 {track.title}')
                        start = sink.tell()
                        runner.run([ffmpeg, '-hide_banner', '-v', 'error', '-i', track.path,
                                    '-map', '0:a:0', '-vn', '-c:a', raw_codec, '-f', raw_fmt, 'pipe:1'], stdout=sink)
                        end = sink.tell()
                        offsets.append((Fraction(start, width * channels * rate),
                                        Fraction(end, width * channels * rate)))
                duration = offsets[-1][1]
                filename = f'{stem}' + (f' - 第{part_no}部分' if len(parts) > 1 else '') + '.mkv'
                target = dest / filename
                log(f'正在合成 {filename}（{clock(duration)}）…')
                cmd = [ffmpeg, '-hide_banner', '-v', 'error', '-y', '-stream_loop', '-1', '-i', still,
                       '-f', raw_fmt, '-ar', str(rate), '-ac', str(channels), '-i', raw,
                       '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', audio_codec]
                if audio_codec == 'flac':
                    cmd += ['-compression_level', '5', '-sample_fmt', 's16' if bits <= 16 else 's32']
                # Round video length UP to a frame; finite audio is neither padded nor trimmed.
                cmd += ['-t', f'{math.ceil(duration * 30) / 30:.9f}', '-metadata', f'title={stem}', target]
                runner.run(cmd)
                text_lines += [f'第 {part_no} 部分：{filename}', f'时长：{clock(duration)}']
                for track, (start, end) in zip(part, offsets):
                    global_index += 1
                    text_lines.append(f'{global_index:02d}. {clock(start)} - {clock(end)}  {track.title}')
                text_lines.append('')
                raw.unlink()
            txt = dest / f'{stem} - 曲目时段.txt'
            txt.write_text('\n'.join(text_lines), encoding='utf-8-sig')
        complete = True
        return dest
    finally:
        if not complete:
            # This directory was exclusively created by this run.
            shutil.rmtree(dest, ignore_errors=True)


class OrderDialog(tk.Toplevel):
    def __init__(self, parent, tracks):
        super().__init__(parent)
        self.title('填写专辑曲序')
        self.geometry('760x540')
        self.minsize(580, 360)
        self.transient(parent)
        self.result = None
        self.tracks = tracks
        ttk.Label(self, text='未读到完整且唯一的曲序。请为每首歌填写顺序数字（1 开始，不重复）。', padding=12).pack(anchor='w')
        frame = ttk.Frame(self)
        frame.pack(fill='both', expand=True, padx=12)
        canvas = tk.Canvas(frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        rows = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=rows, anchor='nw')
        rows.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e: canvas.itemconfigure(window, width=e.width))
        self.values = []
        for i, track in enumerate(tracks):
            value = tk.StringVar(value='')
            self.values.append(value)
            ttk.Entry(rows, textvariable=value, width=6).grid(row=i, column=0, padx=6, pady=6)
            ttk.Label(rows, text=f'{track.title}\n{track.path.name}', wraplength=570).grid(row=i, column=1, sticky='w')
        buttons = ttk.Frame(self, padding=12)
        buttons.pack(fill='x')
        ttk.Button(buttons, text='取消', command=self.destroy).pack(side='right', padx=5)
        ttk.Button(buttons, text='确认顺序', command=self.submit).pack(side='right')
        self.grab_set()
        self.protocol('WM_DELETE_WINDOW', self.destroy)

    def submit(self):
        try:
            self.result = manual_order(self.tracks, [v.get() for v in self.values])
        except ValueError as e:
            messagebox.showerror('顺序无效', str(e), parent=self)
            return
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('专辑音源 → 方形视频')
        self.geometry('850x650')
        self.minsize(700, 520)
        self.events = queue.Queue()
        self.runner = None
        self.busy = False
        self.folder = tk.StringVar()
        self.cover = tk.StringVar()
        self.output = tk.StringVar(value=str(Path.home() / 'Videos' / '专辑视频'))
        self.ffmpeg = tk.StringVar()
        self.force_order = tk.BooleanVar()
        root = ttk.Frame(self, padding=20)
        root.pack(fill='both', expand=True)
        ttk.Label(root, text='把整张专辑做成封面视频', font=('Microsoft YaHei UI', 18, 'bold')).pack(anchor='w')
        ttk.Label(root, text='1080 × 1080 · 30 fps · 无损音频 · 自动生成曲目时段', padding=(0, 8)).pack(anchor='w')
        for label, variable, action in [('音源文件夹', self.folder, self.pick_folder),
                                         ('专辑图片', self.cover, self.pick_cover),
                                         ('输出文件夹', self.output, self.pick_output),
                                         ('FFmpeg（可自动查找）', self.ffmpeg, self.pick_ffmpeg)]:
            row = ttk.Frame(root)
            row.pack(fill='x', pady=5)
            ttk.Label(row, text=label, width=23).pack(side='left')
            ttk.Entry(row, textvariable=variable).pack(side='left', fill='x', expand=True)
            ttk.Button(row, text='选择…', command=action).pack(side='left', padx=(8, 0))
        ttk.Checkbutton(root, text='始终让我检查／填写曲序', variable=self.force_order).pack(anchor='w', pady=6)
        ttk.Label(root, text='超过 1 小时：按歌曲数分成两半，奇数时前半多一首。\n封面按宽度缩放到 1080，再垂直居中裁剪；横图高度不足时上下补黑。').pack(anchor='w', pady=6)
        actions = ttk.Frame(root)
        actions.pack(fill='x', pady=10)
        self.start_button = ttk.Button(actions, text='开始制作', command=self.start)
        self.start_button.pack(side='left')
        self.cancel_button = ttk.Button(actions, text='取消制作', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=10)
        self.progress = ttk.Progressbar(actions, mode='indeterminate')
        self.progress.pack(side='left', fill='x', expand=True)
        self.log_widget = tk.Text(root, height=12, wrap='word', state='disabled', font=('Microsoft YaHei UI', 10))
        self.log_widget.pack(fill='both', expand=True)
        self.after(100, self.poll)
        self.protocol('WM_DELETE_WINDOW', self.close)

    def pick_folder(self):
        p = filedialog.askdirectory(title='选择音源文件夹')
        if p:
            self.folder.set(p)

    def pick_cover(self):
        p = filedialog.askopenfilename(title='选择专辑图片', filetypes=[('图片', '*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff'), ('所有文件', '*.*')])
        if p:
            self.cover.set(p)

    def pick_output(self):
        p = filedialog.askdirectory(title='选择输出文件夹')
        if p:
            self.output.set(p)

    def pick_ffmpeg(self):
        p = filedialog.askopenfilename(title='选择 ffmpeg.exe（同目录需有 ffprobe.exe）', filetypes=[('FFmpeg', 'ffmpeg.exe'), ('所有文件', '*.*')])
        if p:
            self.ffmpeg.set(p)

    def log(self, text):
        self.events.put(('log', text))

    def start(self):
        if self.busy:
            return
        folder, cover, output, tool = [v.get().strip() for v in (self.folder, self.cover, self.output, self.ffmpeg)]
        if not Path(folder).is_dir() or not Path(cover).is_file() or not output:
            messagebox.showerror('请补全选择', '请选择有效的音源文件夹、专辑图片和输出文件夹。', parent=self)
            return
        self.busy = True
        self.runner = Runner()
        self.start_button.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.progress.start()
        force = self.force_order.get()
        def worker():
            try:
                try:
                    ffmpeg, probe = find_tools(tool)
                except ValueError:
                    answer = queue.Queue()
                    self.events.put(('tools', answer))
                    selected = answer.get()
                    if not selected:
                        raise Cancelled()
                    ffmpeg, probe = find_tools(selected)
                self.log(f'使用 FFmpeg：{ffmpeg}')
                tracks = scan(folder, probe, self.runner, self.log)
                ordered = None if force else automatic_order(tracks)
                if ordered is None:
                    answer = queue.Queue()
                    self.events.put(('order', (tracks, answer)))
                    ordered = answer.get()
                    if ordered is None or self.runner.cancel.is_set():
                        raise Cancelled()
                self.log('最终曲序：\n' + '\n'.join(f'{i}. {t.title}' for i, t in enumerate(ordered, 1)))
                self.log(f'总时长：{clock(sum((t.duration for t in ordered), Fraction()))}；输出 {len(split_album(ordered))} 个视频')
                result = render(ordered, cover, output, ffmpeg, self.runner, self.log)
                self.events.put(('done', result))
            except Cancelled:
                self.events.put(('cancelled', None))
            except Exception as e:
                self.events.put(('error', str(e)))
        threading.Thread(target=worker, daemon=True).start()

    def cancel(self):
        if self.runner:
            self.runner.cancel.set()

    def close(self):
        if self.busy:
            self.cancel()
            self.log('正在取消，请等待清理完成后再关闭窗口。')
        else:
            self.destroy()

    def poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'log':
                    self.log_widget.configure(state='normal')
                    self.log_widget.insert('end', value + '\n')
                    self.log_widget.see('end')
                    self.log_widget.configure(state='disabled')
                elif kind == 'tools':
                    self.pick_ffmpeg()
                    value.put(self.ffmpeg.get())
                elif kind == 'order':
                    tracks, answer = value
                    dialog = OrderDialog(self, tracks)
                    self.wait_window(dialog)
                    answer.put(dialog.result)
                elif kind in ('done', 'error', 'cancelled'):
                    self.busy = False
                    self.start_button.configure(state='normal')
                    self.cancel_button.configure(state='disabled')
                    self.progress.stop()
                    if kind == 'done':
                        self.log(f'制作完成：{value}')
                        messagebox.showinfo('制作完成', f'视频和曲目时段已保存到：\n{value}', parent=self)
                        if os.name == 'nt':
                            os.startfile(value)
                    elif kind == 'error':
                        self.log('失败：' + value)
                        messagebox.showerror('制作失败', value, parent=self)
                    else:
                        self.log('已取消，未完成文件已清理。')
        except queue.Empty:
            pass
        self.after(100, self.poll)


def main():
    parser = argparse.ArgumentParser(description='专辑音源合成方形 MKV 视频；不加参数启动窗口。')
    parser.add_argument('--folder')
    parser.add_argument('--cover')
    parser.add_argument('--output')
    parser.add_argument('--ffmpeg', default='')
    parser.add_argument('--order', help='按文件名排序后，各文件对应的顺序数字，用逗号分隔')
    args = parser.parse_args()
    if not args.folder:
        App().mainloop()
        return
    if not args.cover or not args.output:
        parser.error('命令行模式还需 --cover 和 --output')
    ffmpeg, probe = find_tools(args.ffmpeg)
    runner = Runner()
    tracks = scan(args.folder, probe, runner, print)
    tracks = manual_order(tracks, args.order.split(',')) if args.order else automatic_order(tracks)
    if tracks is None:
        parser.error('缺少曲序。请使用窗口程序或传入 --order')
    print(render(tracks, args.cover, args.output, ffmpeg, runner, print))


if __name__ == '__main__':
    main()
