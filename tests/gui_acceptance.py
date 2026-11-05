"""Exercise the actual App worker -> missing metadata -> modal -> render flow."""
import json
from pathlib import Path
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import album_video as av

root = Path(__file__).resolve().parents[1]
app = av.App()
app.title('专辑视频 · 手动排序验收')
app.attributes('-topmost', True)
app.folder.set(str(root / 'acceptance' / 'outer_no_order'))
app.cover.set(str(root / 'acceptance' / '测试封面.png'))
app.output.set(str(root / 'acceptance' / 'manual_output'))
report = {'dialog_appeared': False, 'order_submitted': False, 'completed': False}
mapping = json.loads((root / 'acceptance' / 'verification.json').read_text(encoding='utf-8'))['stripped_order_numbers_by_filename']
seen_at = None


def info(title, text, **kwargs):
    report['completed'] = True
    report['message'] = text
    save()
    app.after(3000, app.destroy)


def error(title, text, **kwargs):
    report['error'] = text
    save()
    app.after(3000, app.destroy)


def save():
    (root / 'acceptance' / 'gui_verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def check():
    global seen_at
    dialogs = [w for w in app.winfo_children() if isinstance(w, av.OrderDialog)]
    if dialogs:
        dialog = dialogs[0]
        if seen_at is None:
            assert all(t.number is None for t in dialog.tracks)
            report['dialog_appeared'] = True
            report['track_count'] = len(dialog.tracks)
            seen_at = time.monotonic()
            save()
        if time.monotonic() - seen_at > 15:
            for t, v in zip(dialog.tracks, dialog.values):
                v.set(str(mapping[t.path.name]))
            dialog.submit()
            report['order_submitted'] = True
            save()
    report['busy'] = app.busy
    save()
    app.after(300, check)


av.messagebox.showinfo = info
av.messagebox.showerror = error
if hasattr(av.os, 'startfile'):
    av.os.startfile = lambda _: None
app.after(300, app.start)
app.after(600, check)
app.mainloop()
