"""Install pinned browser OCR assets. No identity images are sent by this script."""
import base64
import hashlib
import io
import gzip
import json
from pathlib import Path
import tarfile
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / 'static' / 'vendor' / 'identity-ocr'
PACKAGES = [
    ('tesseract.js', '6.0.1', 'https://registry.npmjs.org/tesseract.js/-/tesseract.js-6.0.1.tgz',
     '/sPvMvrCtgxnNRCjbTYbr7BRu0yfWDsMZQ2a/T5aN/L1t8wUQN6tTWv6p6FwzpoEBA0jrN2UD2SX4QQFRdoDbA=='),
    ('tesseract.js-core', '6.0.0', 'https://registry.npmjs.org/tesseract.js-core/-/tesseract.js-core-6.0.0.tgz',
     '1Qncm/9oKM7xgrQXZXNB+NRh19qiXGhxlrR8EwFbK5SaUbPZnS5OMtP/ghtqfd23hsr1ZvZbZjeuAGcMxd/ooA=='),
    ('@tesseract.js-data/vie', '1.0.0', 'https://registry.npmjs.org/@tesseract.js-data/vie/-/vie-1.0.0.tgz',
     'hFxBtxSiCw6+64uxf0psrlLvcYA5kQimYhTSx1RwjbD5jSxe1bWg3EmipAozkzELQIFAMkJC5vu+ONGRem7YLA=='),
]


def main():
    collected = {}
    manifest = {'packages': [], 'files': {}}
    for name, version, url, digest in PACKAGES:
        print(f'Downloading {name} {version}...', flush=True)
        with urlopen(url, timeout=60) as response:
            package = response.read()
        if base64.b64encode(hashlib.sha512(package).digest()).decode() != digest:
            raise RuntimeError(f'Package integrity verification failed: {name}')
        with tarfile.open(fileobj=io.BytesIO(package), mode='r:gz') as archive:
            package_info = json.load(archive.extractfile('package/package.json'))
            manifest['packages'].append({'name': name, 'version': version, 'url': url,
                'integrity': 'sha512-' + digest, 'license': package_info.get('license')})
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                target = None
                if name == 'tesseract.js' and member.name in ('package/dist/tesseract.min.js', 'package/dist/worker.min.js'):
                    target = Path(member.name).name
                elif name == 'tesseract.js-core' and member.name.startswith('package/tesseract-core') and member.name.endswith(('.wasm', '.wasm.js')):
                    target = 'core/' + Path(member.name).name
                elif name == '@tesseract.js-data/vie' and member.name == 'package/4.0.0_best_int/vie.traineddata.gz':
                    target = 'lang/vie.traineddata'
                elif Path(member.name).name.upper() in ('LICENSE', 'LICENSE.MD', 'LICENSE.TXT', 'NOTICE'):
                    target = 'licenses/' + name.replace('@', '').replace('/', '-') + '-' + Path(member.name).name
                if target:
                    content = archive.extractfile(member).read()
                    collected[target] = gzip.decompress(content) if target == 'lang/vie.traineddata' else content
    required = {'tesseract.min.js', 'worker.min.js', 'lang/vie.traineddata'}
    for variant in ('', '-simd', '-lstm', '-simd-lstm'):
        required.update({f'core/tesseract-core{variant}.wasm', f'core/tesseract-core{variant}.wasm.js'})
    if not required.issubset(collected):
        raise RuntimeError('Missing OCR files: ' + ', '.join(sorted(required - collected.keys())))
    for name, data in collected.items():
        target = DESTINATION / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest['files'][name] = hashlib.sha256(data).hexdigest()
    (DESTINATION / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f'Installed {len(collected)} verified assets in {DESTINATION}', flush=True)


if __name__ == '__main__':
    main()
