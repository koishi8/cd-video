# cd-video · 专辑视频制作

从 [ver1.0 发行版](https://github.com/koishi8/cd-video/releases/tag/ver1.0) 下载 `AlbumVideo.exe`，双击即可打开窗口，无需安装 Python。也可下载 `cd-video-ver1.0-windows-x64.zip`，解压后运行。

需要另外准备包含 `ffmpeg.exe` 和 `ffprobe.exe` 的 FFmpeg 工具包；发行版未内置 FFmpeg。

1. 选择放有 FLAC / WAV 的音源文件夹（只读取本层文件）。
2. 选择专辑图片和输出文件夹。
3. FFmpeg 会自动从程序目录、程序目录下 `ffmpeg/bin` 或 PATH 查找。找不到时会弹出文件选择窗口，让你指定 `ffmpeg.exe`；同目录还需有 `ffprobe.exe`。
4. 点击“开始制作”。缺少曲序标签、标签不完整或曲序重复时，会弹出窗口，列出所有曲名及文件名。为每首填写 1 至歌曲总数的顺序数字，不得重复。也可勾选“始终让我检查／填写曲序”。

## 输出规则

- MKV，1080×1080，30fps，H.264 画面。
- 图片保持比例缩放至宽 1080，再垂直居中裁剪到 1080 高。横图缩放后高度不足时，上下补黑，避免额外拉伸失真。
- 16/24 位整数音源编码为无损 FLAC，保留采样率、声道数和所有音频样本。32 位整数和浮点 WAV 使用无损 PCM，文件较大。
- 优先使用音源内的曲序标签；多碟专辑使用碟号、曲号排序。文件名中的数字不充当标签，标签不足时交由用户确认。
- 总时长严格超过 3600 秒时，按歌曲数量拆成两段。13 首为 1–7、8–13；14 首为 1–7、8–14。分段依据歌曲数，因此极端情况下单段仍可能超过一小时。
- TXT 列出每部分的文件名及每首歌在该视频中的起止时间。时间从各视频的零点开始，按真实音频样本累计后向下取整到秒，格式为 HH:MM:SS。结束点是下一首的起点。
- 输出到独立的专辑子文件夹。已有同名文件夹时增加数字后缀，不覆盖。
- 可取消制作，失败或取消时清理本次未完成结果。原始音源和封面不作修改。

音源采样率或声道数不一致时会提示错误，不自动重采样。单首音源超过一小时无法按歌曲拆成两半，会提示先分轨。制作时需要临时磁盘空间保存一部分专辑的解码音频（CD 音源通常数百 MB）。

## 已完成的实际验收

验收使用测试封面，输出写入本地 `acceptance` 文件夹。测试音源、封面及生成视频不随源码或发行版上传。

| 输入 | 结果 | 音频时长（秒向下取整） |
| --- | --- | --- |
| `F:\CD\regret\I've\regret ～I've GIRLS COMPILATION Vol. 1` | 两段 MKV + TXT，前 7 首、后 6 首 | 31:41 / 31:56 |
| `F:\CD\outer` | 一段 MKV + TXT | 32:09 |
| `acceptance/outer_no_order`（复制 Outer 并移除元数据） | 实际窗口自动弹出，填写顺序后完成 MKV + TXT | 32:09 |

`acceptance/verification.json` 记录分辨率、帧率、曲目及完整解码音频 SHA-256。三个原专辑输出均与对应原曲连续解码后的 PCM 哈希、样本数完全一致，TXT 内容逐行校验通过。手动排序输出也与原 Outer 专辑的 PCM 哈希一致。`acceptance/gui_verification.json` 记录真实窗口流程的验收结果。

## 源代码运行与检查

程序源代码为 `album_video.py`，运行时仅使用 Python 标准库和外部 FFmpeg。支持 Python 3.10 及以上版本。

```powershell
python album_video.py
python -m unittest discover -s tests -p test_core.py -v
python tests/acceptance_check.py
python tests/gui_acceptance.py
```

`tests/gui_acceptance.py` 会在真实窗口弹出曲序表后自动填入已知正确顺序，执行完整合成并记录结果。正常软件不会自动填入缺失曲序。

完整专辑和窗口验收需要上述本地音源路径，以及 `acceptance/测试封面.png`；先运行 `tests/acceptance_check.py`，再运行窗口验收。普通单元测试不需要音源。

Windows EXE 的构建方法见 [BUILD.md](BUILD.md)。

也支持命令行制作：

```powershell
python album_video.py --folder "F:\CD\outer" --cover "D:\cover.jpg" --output "D:\output"
```

可加 `--ffmpeg "D:\tools\ffmpeg.exe"`；缺少曲序时，可加 `--order "3,8,6,7,1,4,5,2"`（每个数字对应按文件名排序后的文件）。
