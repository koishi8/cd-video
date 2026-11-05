"""Run full-file lossless checks against the user's real albums."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from album_video import *

ROOT = Path(__file__).resolve().parents[1]
FFMPEG, PROBE = find_tools()


def digest(paths):
    h = hashlib.sha256()
    size = 0
    for path in paths:
        with tempfile.TemporaryFile() as errors:
            p = subprocess.Popen([str(FFMPEG), '-v', 'error', '-i', str(path), '-map', '0:a:0',
                                  '-f', 's16le', '-c:a', 'pcm_s16le', 'pipe:1'],
                                 stdout=subprocess.PIPE, stderr=errors, creationflags=CREATE_FLAGS)
            while data := p.stdout.read(1024 * 1024):
                h.update(data)
                size += len(data)
            if p.wait():
                errors.seek(0)
                raise RuntimeError(errors.read())
    return {'sha256': h.hexdigest(), 'samples_per_channel': size // 4}


def verify(source, result):
    tracks = automatic_order(scan(source, PROBE, Runner()))
    assert tracks
    groups = split_album(tracks)
    videos = sorted(Path(result).glob('*.mkv'))
    assert len(videos) == len(groups)
    report = []
    lines = [tracks[0].path.parent.name,
             '时间格式 HH:MM:SS；每个时间点均向下取整；结束时间为下一首的起点。', '']
    idx = 0
    for part_no, (group, video) in enumerate(zip(groups, videos), 1):
        info = json.loads(Runner().run([PROBE, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', video]))
        v = next(s for s in info['streams'] if s['codec_type'] == 'video')
        a = next(s for s in info['streams'] if s['codec_type'] == 'audio')
        assert (v['width'], v['height'], Fraction(v['r_frame_rate'])) == (1080, 1080, 30)
        assert a['codec_name'] == 'flac' and a['sample_rate'] == '44100' and a['channels'] == 2
        original = digest([t.path for t in group])
        actual = digest([video])
        assert original == actual, (video, original, actual)
        duration = sum((t.duration for t in group), Fraction())
        lines += [f'第 {part_no} 部分：{video.name}', f'时长：{clock(duration)}']
        elapsed = Fraction()
        for t in group:
            idx += 1
            lines.append(f'{idx:02d}. {clock(elapsed)} - {clock(elapsed + t.duration)}  {t.title}')
            elapsed += t.duration
        lines.append('')
        report.append({'video': str(video), 'tracks': [t.title for t in group], 'seconds': float(duration),
                       'resolution': '1080x1080', 'fps': 30, 'audio': a['codec_name'], 'pcm': actual})
    txt = next(Path(result).glob('*.txt')).read_text(encoding='utf-8-sig')
    assert txt == '\n'.join(lines)
    return report


if __name__ == '__main__':
    sources = [Path("F:/CD/regret/I've/regret ～I've GIRLS COMPILATION Vol. 1"), Path('F:/CD/outer')]
    report = {}
    for source in sources:
        print('Verifying', source, flush=True)
        report[source.name] = verify(source, ROOT / 'acceptance' / source.name)
    stripped = ROOT / 'acceptance' / 'outer_no_order'
    stripped.mkdir(exist_ok=True)
    for path in sources[1].glob('*.wav'):
        target = stripped / path.name
        if not target.exists():
            Runner().run([FFMPEG, '-v', 'error', '-y', '-i', path, '-map', '0:a:0', '-map_metadata', '-1', '-c:a', 'copy', target])
    tracks = scan(stripped, PROBE, Runner())
    assert all(t.number is None for t in tracks)
    assert automatic_order(tracks) is None
    original = automatic_order(scan(sources[1], PROBE, Runner()))
    numbers = {t.path.name: i for i, t in enumerate(original, 1)}
    ordered = manual_order(tracks, [str(numbers[t.path.name]) for t in tracks])
    assert [t.path.name for t in ordered] == [t.path.name for t in original]
    report['stripped_order_numbers_by_filename'] = {t.path.name: numbers[t.path.name] for t in tracks}
    (ROOT / 'acceptance' / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('PASS: real albums, audio PCM hashes, video specs, exact timeline, stripped metadata detection', flush=True)
