#!/usr/bin/env python3
"""Normalize acquired, licensed masters into the launch's 1080p/24 SDR scope."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'tos-action': 'athletic-action-1080p24-final',
    'chimera-natural': 'natural-detail-1080p24-final',
    'nocturne': 'film-grain-1080p24-final',
    'nocturne-dark': 'dark-gradients-1080p24-final',
    'sol-levante-flat': 'animation-1080p24-final',
}
SOURCES['screen'] = 'screen-text-1080p24-final'
SOURCES['tos-dialog'] = 'talking-head-1080p24-final'


def sha(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sources', nargs='*', choices=list(SOURCES))
    parser.add_argument('--ffmpeg', type=Path, default=ROOT / '.build/runtime-macos-old/ffmpeg',
                        help='Exact preparation runtime from the retained ce9d181444 archive; distinct from the newer measurement runtime.')
    args = parser.parse_args()
    binary = args.ffmpeg.resolve()
    assert sha(binary) == '681435111386b2f967d2ae6bb8ed04ea31b813066898824c6c817656a9710af6', 'preparation runtime differs from recorded source preparation'
    output = ROOT / '.build/canonical-prepared'
    output.mkdir(parents=True, exist_ok=True)
    for key in args.sources or SOURCES:
        source = ROOT / ('.build/canonical-screen/screen-workload.mkv' if key == 'screen'
                         else f'.build/canonical-sources/{key}/{key}-source.mkv')
        target = output / (SOURCES[key] + '.mkv')
        if key == 'screen':
            filters = 'setsar=1'
            transform = 'Already converted from sRGB browser PNGs to BT.709 limited using the pinned capture preparation; no rescaling.'
        elif key == 'chimera-natural':
            filters = ('fps=24:start_time=0,zscale=primariesin=smpte432:transferin=smpte2084:matrixin=gbr:rangein=full:'
                       'primaries=smpte432:matrix=gbr:range=full:transfer=linear:npl=100,format=gbrpf32le,zscale=primaries=bt709,'
                       'tonemap=tonemap=hable:desat=0:peak=40,'
                       'zscale=transfer=bt709:matrix=bt709:range=limited:dither=error_diffusion,'
                       'scale=1920:1012:flags=lanczos,format=yuv420p,pad=1920:1080:0:34:black,setsar=1')
            transform = ('P3-D65/PQ RGB16 display master converted through linear light at100nit reference white, BT.709 primaries, '
                         'Hable tone map with fixed4000nit input peak, desaturation disabled, BT.709 limited8-bit4:2:0. '
                         '4096x2160 resized to1920x1012 with even-pixel rounding(<0.05% aspect change),34pixel bars preserve framing. '
                         '24000/1001 to24fps explicit frame selection, no interpolation. Peak is an explicit preparation choice pending visual acceptance, not claimed source metadata.')
        elif key.startswith('tos-'):
            filters = ('zscale=primariesin=bt709:transferin=iec61966-2-1:matrixin=gbr:rangein=full:'
                       'primaries=bt709:transfer=bt709:matrix=bt709:range=limited:dither=error_diffusion,'
                       'format=yuv420p,pad=1920:1080:0:140:black,setsar=1')
            transform = ('Publisher 1920x800 RGB PNG display master treated as sRGB; explicit sRGB transfer to BT.709 limited conversion '
                         'with error diffusion to 8-bit 4:2:0. Preserve all source pixels/aspect; 140-pixel bars top/bottom; no crop or stretch. '
                         'Scope includes cinematic letterboxing, which reduces active pixels and must be considered when interpreting full-frame metrics.')
        else:
            filters = ('scale=1920:1080:flags=lanczos:in_range=tv:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,'
                       'format=yuv420p,setsar=1')
            transform = 'Documented SDR BT.709 limited ProRes master downsampled 3840x2160 to1920x1080 Lanczos, 10-bit4:2:2 to8-bit4:2:0; no denoise.'
            if key.startswith('nocturne'):
                filters = 'fps=24:start_time=0,' + filters
                transform += ' Native60fps reduced to24fps by explicit frame selection; no interpolation or temporal looping. Added-grain source retained.'
        # FFV1 also preserves frame-level color fields: output codec flags alone
        # do not fill a source's missing transfer field.
        filters += ',setparams=range=limited:color_primaries=bt709:color_trc=bt709:colorspace=bt709'
        command = [str(binary), '-y', '-hide_banner', '-i', str(source), '-map', '0:v:0',
                   '-vf', filters, '-frames:v', '240', '-c:v', 'ffv1', '-level', '3', '-g', '1',
                   '-slicecrc', '1', '-pix_fmt', 'yuv420p', '-color_range', 'tv', '-colorspace', 'bt709',
                   '-color_primaries', 'bt709', '-color_trc', 'bt709', '-map_metadata', '-1',
                   '-fflags', '+bitexact', '-flags:v', '+bitexact', '-an', '-sn', '-dn', str(target)]
        record = {'source': str(source.relative_to(ROOT)), 'sourceSha256': sha(source),
                  'finalId': SOURCES[key], 'command': command, 'transformation': transform,
                  'runtimeSha256': sha(binary)}
        with (output / (key + '.log')).open('w') as log:
            subprocess.run(command, stdout=log, stderr=log, check=True)
        record.update({'sha256': sha(target), 'byteSize': target.stat().st_size})
        (output / (key + '-preparation.json')).write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
