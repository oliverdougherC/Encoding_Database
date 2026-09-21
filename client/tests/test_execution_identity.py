import struct
from unittest import mock

import pytest

from client import identity


def pe_header(machine):
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<H', data, 132, machine)
    return data


def test_windows_pe_and_amd64_alias_do_not_require_file_command(tmp_path):
    executable = tmp_path/'ffmpeg.exe'
    executable.write_bytes(pe_header(0x8664))
    identity.runtime_identity.cache_clear()
    try:
        with mock.patch.object(identity.config, 'ffmpeg_exe', return_value=str(executable)), mock.patch.object(identity.config, 'ffprobe_exe', return_value=str(executable)), mock.patch.object(identity.platform, 'machine', return_value='AMD64'), mock.patch.object(identity.platform, 'system', return_value='Windows'), mock.patch.object(identity, '_command') as external:
            value = identity.execution_provenance()
        assert value['executionArchitecture'] == 'x86_64'
        assert value['translationMode'] == 'native'
        assert value['runtimeIdentity']['clientExecutionArchitecture'] == 'x86_64'
        external.assert_not_called()
    finally:
        identity.runtime_identity.cache_clear()


@pytest.mark.parametrize('machine,expected', [(0xAA64,'arm64'), (0x14C,'x86'), (0x1234,'unknown')])
def test_pe_machine_types_are_read_from_bytes(tmp_path, machine, expected):
    path = tmp_path/'helper.exe'
    path.write_bytes(pe_header(machine))
    assert identity.executable_architectures(path) == [expected]


def test_elf_macho_and_universal_headers(tmp_path):
    path = tmp_path/'helper'
    elf = bytearray(64)
    elf[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', elf, 18, 183)
    path.write_bytes(elf)
    assert identity.executable_architectures(path) == ['arm64']
    macho = bytearray(32)
    macho[:4] = b'\xcf\xfa\xed\xfe'
    struct.pack_into('<I', macho, 4, 0x0100000C)
    path.write_bytes(macho)
    assert identity.executable_architectures(path) == ['arm64']
    universal = bytearray(48)
    universal[:4] = b'\xca\xfe\xba\xbe'
    struct.pack_into('>I', universal, 4, 2)
    struct.pack_into('>I', universal, 8, 0x01000007)
    struct.pack_into('>I', universal, 28, 0x0100000C)
    path.write_bytes(universal)
    assert identity.executable_architectures(path) == ['arm64','x86_64']
    with mock.patch.object(identity, 'runtime_identity', return_value={'ffmpeg': {'architectures': ['arm64','x86_64']}}), mock.patch.object(identity.platform, 'machine', return_value='arm64'), mock.patch.object(identity.platform, 'system', return_value='Darwin'), mock.patch.object(identity, '_command', return_value='1'):
        assert identity.execution_provenance()['translationMode'] == 'unknown'


def test_unknown_binary_does_not_inherit_host_native_claim(tmp_path):
    path = tmp_path/'helper.exe'
    path.write_bytes(b'not an executable header')
    assert identity.executable_architectures(path) == ['unknown']
    with mock.patch.object(identity, 'runtime_identity', return_value={'ffmpeg': {'architectures': ['unknown']}}), mock.patch.object(identity.platform, 'machine', return_value='AMD64'), mock.patch.object(identity.platform, 'system', return_value='Windows'):
        assert identity.execution_provenance()['translationMode'] == 'unknown'
    assert identity.normalize_architecture('aarch64') == 'arm64'
