#!/usr/bin/env python3
"""Create a local, reviewable overlay from explicitly observed coordinates; no recognition."""
from __future__ import annotations
import argparse
import base64
import hashlib
import html
import json
import math
import re
import sys
sys.dont_write_bytecode = True
from pathlib import Path
from visual_intake import inspect_image, IntakeError, REGIONS
from fortune import validate_save_path


def validate_annotations(system, entries, width, height, *, labeled=False):
    """Validate original-pixel coordinates; return only the allowed vector data."""
    if not isinstance(system, str) or system not in REGIONS or not isinstance(entries, list) or len(entries) > 100:
        raise ValueError('annotations must contain at most 100 entries for palm or face.')
    clean_entries = []
    for item in entries:
        required = {'region', 'geometry', 'points'} | ({'label', 'observation'} if labeled else set())
        if not isinstance(item, dict) or set(item) != required:
            raise ValueError('Invalid annotation fields.')
        region, geometry, points = item['region'], item['geometry'], item['points']
        if not isinstance(region, str) or region not in REGIONS[system] or geometry not in ('polyline', 'polygon'):
            raise ValueError('Invalid region or geometry.')
        if not isinstance(points, list) or not (2 if geometry == 'polyline' else 3) <= len(points) <= 1000:
            raise ValueError('Invalid point count.')
        clean = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError('Each point must be [x, y].')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in point):
                raise ValueError('Coordinates must be finite numbers.')
            if not 0 <= point[0] <= width or not 0 <= point[1] <= height:
                raise ValueError('Coordinates must lie within the image bounds.')
            clean.append(list(point))
        if len(set(map(tuple, clean))) < (2 if geometry == 'polyline' else 3):
            raise ValueError('Annotation needs distinct points.')
        entry = {'region': region, 'geometry': geometry, 'points': clean}
        if labeled:
            for key, limit in (('label', 80), ('observation', 500)):
                if key not in item:
                    continue
                value = item[key]
                if (not isinstance(value, str) or not 1 <= len(value.strip()) <= limit
                        or any(ord(c) < 32 for c in value)
                        or re.search(r'[A-Za-z]:[\\/]|\\\\|(?:file|https?)://|/(?:Users|home|tmp)/', value, re.I)):
                    raise ValueError('Annotation labels must be short text without private paths.')
                entry[key] = value.strip()
        clean_entries.append(entry)
    return clean_entries


def illustration_html(image, system, translate=lambda value:value):
    """Offline reader markup; the source photo and the vector layer remain separate."""
    caption = image['caption']
    src = image['src']
    if not re.fullmatch(r'data:image/(?:png|jpeg|webp);base64,[a-zA-Z0-9+/=]+', src):
        raise ValueError('Illustrations require an inline raster image.')
    if image.get('kind') != 'photo_annotation':
        prefix = '原图AI标注 · ' if image.get('kind') == 'generated_photo_annotation' else 'AI分析示意图 · '
        translated_prefix=translate(prefix)
        label = translated_prefix+(caption[len(prefix):] if caption.startswith(prefix) else caption[len(translated_prefix):] if caption.startswith(translated_prefix) else caption)
        return '<figure><img src="'+html.escape(src, quote=True)+'" alt="'+html.escape(caption, quote=True)+'"><figcaption>'+html.escape(label)+'</figcaption></figure>'
    overlay = image['overlay']
    width, height = overlay['width'], overlay['height']
    if any(type(v) is not int or v <= 0 for v in (width, height)) or width*height > 100_000_000:
        raise ValueError('Invalid original photo dimensions.')
    entries = validate_annotations(system, overlay['annotations'], width, height, labeled=True)
    shapes, descriptions = [], []
    radius = min(width, height)/50
    for number, item in enumerate(entries, 1):
        points = ' '.join(f'{x},{y}' for x,y in item['points'])
        x, y = item['points'][0]
        shapes.append(f'<{item["geometry"]} points="{points}" fill="none" stroke="#B94336" stroke-width="{min(width,height)/450}" stroke-linecap="round" stroke-linejoin="round"/>')
        shapes.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="#FAF4EB" stroke="#B94336" stroke-width="{min(width,height)/450}"/><text x="{x}" y="{y}" dy=".35em" text-anchor="middle" fill="#8E3029" font-family="sans-serif" font-size="{radius*1.4}">{number}</text>')
        descriptions.append('<li><strong>'+html.escape(item['label'])+'</strong>：'+html.escape(item['observation'])+'</li>')
    prefix='原图标注 · ';translated_prefix=translate(prefix)
    label=translated_prefix+(caption[len(prefix):] if caption.startswith(prefix) else caption[len(translated_prefix):] if caption.startswith(translated_prefix) else caption)
    return ('<figure class="photo-annotation"><div class="photo-annotation-frame"><img src="'+html.escape(src,quote=True)+'" alt="'+html.escape(caption,quote=True)+'">'
            +f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="'+html.escape(translate('照片标注'),quote=True)+'">'+''.join(shapes)+'</svg></div>'
            +'<figcaption>'+html.escape(label)+'</figcaption><ol class="photo-annotation-key">'+''.join(descriptions)+'</ol></figure>')


def render(image_path: Path, data: dict, annotation_path: Path) -> str:
    if not image_path.is_absolute() or not annotation_path.is_absolute():
        raise ValueError('Image and annotation paths must be absolute.')
    image_path = image_path.resolve(strict=True)
    annotation_path = annotation_path.resolve(strict=True)
    info, _ = inspect_image(image_path)
    if info['orientation'] not in (None, 1):
        raise ValueError('Non-default EXIF orientation: use a visually verified orientation-normalized copy first.')
    image = image_path.read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    if digest != info['sha256']:
        raise ValueError('Image changed during inspection.')
    if not isinstance(data, dict) or set(data) != {'system', 'image_sha256', 'observation_source', 'annotations'}:
        raise ValueError('Expected system, image_sha256, observation_source and annotations.')
    system = data['system']
    if system not in REGIONS or data['image_sha256'] != digest:
        raise ValueError('Unsupported system or image SHA-256 mismatch.')
    if data['observation_source'] not in ('user_visual_observation', 'assistant_visual_observation'):
        raise ValueError('Specify who actually observed the image.')
    width, height = info['width'], info['height']
    entries = validate_annotations(system, data['annotations'], width, height)
    shapes, descriptions = [], []
    for index, item in enumerate(entries, 1):
        region, geometry, points = item['region'], item['geometry'], item['points']
        clean = [f'{x:.3f},{y:.3f}' for x,y in points]
        shapes.append(f'<{geometry} points="{" ".join(clean)}" fill="none" stroke="#ff2727" stroke-width="{max(1, min(width,height)/300):.2f}" vector-effect="non-scaling-stroke"/>')
        descriptions.append(f'<li>{index}: {html.escape(region)} ({geometry}) — {html.escape(json.dumps(points, ensure_ascii=True))}</li>')
    mime = 'image/png' if info['format'] == 'PNG' else 'image/jpeg'
    payload = base64.b64encode(image).decode('ascii')
    paths = f'图像：{html.escape(str(image_path))}；标注输入：{html.escape(str(annotation_path))}'
    source = html.escape(data['observation_source'])
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'"><title>人工观察标注</title><style>body{{font-family:sans-serif;margin:1.5em}} .frame{{position:relative;display:inline-block;max-width:100%}}img{{display:block;max-width:100%;height:auto}}svg{{position:absolute;inset:0;width:100%;height:100%}}p{{overflow-wrap:anywhere}}</style></head><body><h1>人工观察标注</h1><p>这些标注来自显式观察输入，未经自动识别或验证；无法辨认的区域不应补画。</p><p>{paths}</p><p>SHA-256: {digest}；观察来源：{source}；坐标：原图左上为 (0,0)，横向 x、纵向 y，单位像素。画布 {width} × {height}。</p><div class="frame"><img src="data:{mime};base64,{payload}" alt="待审阅图像"><svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" aria-label="人工标注">{''.join(shapes)}</svg></div><ol>{''.join(descriptions)}</ol></body></html>'''


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--annotations', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    try:
        if not a.annotations.is_absolute() or a.annotations.stat().st_size > 1_000_000:
            raise ValueError('Annotations require an absolute JSON path of at most 1 MB.')
        data = json.loads(a.annotations.read_text(encoding='utf-8-sig'))
        target = validate_save_path(a.output)
        if target.suffix.lower() != '.html':
            raise ValueError('Output must be a new .html file.')
        result = render(a.image, data, a.annotations)
        with target.open('x', encoding='utf-8', newline='\n') as handle:
            handle.write(result)
        print(json.dumps({'ok': True, 'output': str(target.resolve()), 'uploaded': False, 'automatic_recognition': False}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, IntakeError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        return 2

if __name__ == '__main__':
    sys.exit(main())
