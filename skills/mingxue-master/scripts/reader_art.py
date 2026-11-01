"""Package-authored illustrations, embedded offline without prompts or local paths."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
KEYS={"hero","tarot_major","tarot_suits","lenormand","card_back","coins",
      "tarot_wands","tarot_cups","tarot_swords","tarot_pentacles"}
MAX_BYTES=12*1024*1024


def art_bundle(systems=None,tarot_cards=None):
    manifest=ROOT/'assets/art-manifest.json'
    if not manifest.is_file():
        return {}
    value=json.loads(manifest.read_text(encoding='utf-8'))
    if value.get('schema_version')!=1 or not isinstance(value.get('assets'),list):
        raise ValueError('Invalid packaged illustration manifest')
    selected=set(KEYS) if systems is None else {'hero'}
    if systems is not None:
        systems=set(systems)
        if 'tarot' in systems:
            if tarot_cards is None:
                selected.update({'tarot_major','tarot_suits','tarot_wands','tarot_cups','tarot_swords','tarot_pentacles'})
            else:
                ids={card.get('id','') for card in tarot_cards if isinstance(card,dict)}
                if any(i.startswith('major-') for i in ids):selected.add('tarot_major')
                for suit in ('wands','cups','swords','pentacles'):
                    if any(i.startswith(suit+'-') for i in ids):selected.add('tarot_'+suit)
        if 'lenormand' in systems:selected.add('lenormand')
    result={};seen=set()
    for entry in value['assets']:
        key=entry.get('key')
        if key not in KEYS or key in seen:
            raise ValueError('Unexpected or duplicate packaged illustration')
        seen.add(key)
        if key not in selected:
            continue
        relative=Path(entry['path'])
        source=ROOT/relative
        if relative.is_absolute() or source.is_symlink() or not source.resolve().is_relative_to((ROOT/'assets/art').resolve()):
            raise ValueError('Illustration must stay inside packaged art')
        if not source.is_file() or source.stat().st_size>MAX_BYTES:
            raise ValueError('Packaged illustration missing or too large')
        raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry.get('sha256'):
            raise ValueError('Packaged illustration changed')
        mime='image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else None
        if mime is None:
            raise ValueError('Unsupported packaged illustration format')
        record={'src':'data:'+mime+';base64,'+base64.b64encode(raw).decode('ascii'),
                'width':entry['width'],'height':entry['height'],'alt':entry.get('alt','')}
        if isinstance(entry.get('atlas'),dict):
            atlas=entry['atlas']
            record['atlas']={k:atlas[k] for k in ('cols','rows','index_mapping','tiles','verified_for_card_binding') if k in atlas}
        result[key]=record
    return result


def write_intake_bundle():
    target=ROOT/'ui/art-assets.js'
    assets=art_bundle()
    entries=json.loads((ROOT/'assets/art-manifest.json').read_text(encoding='utf-8'))['assets'] if assets else []
    for entry in entries:
        assets[entry['key']]['src']='/art/'+Path(entry['path']).name
    text=json.dumps(assets,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    text=text.replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    rendered='window.MingxueArt='+text+';\n'
    if not target.exists() or target.read_text(encoding='utf-8')!=rendered:
        target.write_text(rendered,encoding='utf-8')
    return target
