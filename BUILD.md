# 构建 Windows 发行版

需要 Windows x64、Python 3.10 或更新版本（含 Tkinter）。推荐使用标准 Python 安装包，在独立虚拟环境中构建。

在仓库根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pyinstaller==6.22.3
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_core.py -v
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean AlbumVideo.spec
```

生成的 `dist/AlbumVideo.exe` 为无控制台窗口的单文件程序，运行时不需要 Python。FFmpeg 和 FFprobe 不内置，程序会自动查找，或让用户手动指定。

发布前在 Windows 上启动 EXE，确认文件选择和曲序窗口正常；有测试素材时按 README 执行完整音频与窗口验收。
