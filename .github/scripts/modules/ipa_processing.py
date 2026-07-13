import hashlib
import os
import plistlib
import re
import shutil
import struct
import tempfile
import zipfile

from utils import logger

_MH_MAGIC_64 = 0xFEEDFACF
_MH_MAGIC_32 = 0xFEEDFACE
_FAT_MAGIC = 0xCAFEBABE
_FAT_MAGIC_64 = 0xCAFEBABF
_LC_CODE_SIGNATURE = 0x1D
_CSMAGIC_EMBEDDED_SIGNATURE = 0xFADE0CC0
_CSMAGIC_ENTITLEMENTS = 0xFADE7171

_EXCLUDED_ENTITLEMENTS = {
    'com.apple.developer.team-identifier',
    'application-identifier',
}

def _find_macho_slice(data):
    if len(data) < 4:
        return None
    magic = struct.unpack_from('>I', data, 0)[0]
    if magic in (_FAT_MAGIC, _FAT_MAGIC_64):
        nfat = struct.unpack_from('>I', data, 4)[0]
        best = None
        for i in range(nfat):
            if magic == _FAT_MAGIC:
                base = 8 + i * 20
                cpu_type = struct.unpack_from('>I', data, base)[0]
                offset = struct.unpack_from('>I', data, base + 8)[0]
                size = struct.unpack_from('>I', data, base + 12)[0]
            else:
                base = 8 + i * 32
                cpu_type = struct.unpack_from('>I', data, base)[0]
                offset = struct.unpack_from('>Q', data, base + 8)[0]
                size = struct.unpack_from('>Q', data, base + 16)[0]
            if cpu_type == 0x100000C:
                return (offset, size)
            if best is None:
                best = (offset, size)
        return best
    magic_le = struct.unpack_from('<I', data, 0)[0]
    if magic_le in (_MH_MAGIC_64, _MH_MAGIC_32) or magic in (_MH_MAGIC_64, _MH_MAGIC_32):
        return (0, len(data))
    return None

def _parse_code_signature(cs_data):
    entitlements = set()
    if len(cs_data) < 12:
        return entitlements
    magic = struct.unpack_from('>I', cs_data, 0)[0]
    if magic != _CSMAGIC_EMBEDDED_SIGNATURE:
        return entitlements
    count = struct.unpack_from('>I', cs_data, 8)[0]
    for i in range(count):
        idx_off = 12 + i * 8
        if idx_off + 8 > len(cs_data):
            break
        blob_offset = struct.unpack_from('>I', cs_data, idx_off + 4)[0]
        if blob_offset + 8 > len(cs_data):
            continue
        blob_magic = struct.unpack_from('>I', cs_data, blob_offset)[0]
        blob_length = struct.unpack_from('>I', cs_data, blob_offset + 4)[0]
        if blob_magic == _CSMAGIC_ENTITLEMENTS:
            plist_data = cs_data[blob_offset + 8:blob_offset + blob_length]
            try:
                ent_dict = plistlib.loads(plist_data)
                for key in ent_dict:
                    if key not in _EXCLUDED_ENTITLEMENTS:
                        entitlements.add(key)
            except Exception:
                pass
    return entitlements

def _extract_entitlements_from_macho(data):
    slice_info = _find_macho_slice(data)
    if not slice_info:
        return set()
    offset, size = slice_info
    macho = data[offset:offset + size]
    if len(macho) < 32:
        return set()
    magic = struct.unpack_from('<I', macho, 0)[0]
    if magic == _MH_MAGIC_64:
        header_size = 32
    elif magic == _MH_MAGIC_32:
        header_size = 28
    else:
        return set()
    ncmds = struct.unpack_from('<I', macho, 16)[0]
    pos = header_size
    cs_offset = cs_size = None
    for _ in range(ncmds):
        if pos + 8 > len(macho):
            break
        cmd = struct.unpack_from('<I', macho, pos)[0]
        cmdsize = struct.unpack_from('<I', macho, pos + 4)[0]
        if cmd == _LC_CODE_SIGNATURE:
            cs_offset = struct.unpack_from('<I', macho, pos + 8)[0]
            cs_size = struct.unpack_from('<I', macho, pos + 12)[0]
            break
        pos += cmdsize
    if cs_offset is None:
        return set()
    cs_data = macho[cs_offset:cs_offset + cs_size]
    return _parse_code_signature(cs_data)

def parse_ipa(ipa_path, default_bundle_id):
    result = {
        'version': None, 'build': None,
        'bundle_id': default_bundle_id, 'min_os_version': None,
        'permissions': {'entitlements': [], 'privacy': {}},
        'is_valid': False,
    }
    all_entitlements = set()
    all_privacy = {}

    try:
        with zipfile.ZipFile(ipa_path, 'r') as zf:
            names = zf.namelist()

            app_prefix = None
            for n in names:
                m = re.match(r'^Payload/([^/]+\.app)/', n)
                if m:
                    app_prefix = f"Payload/{m.group(1)}"
                    break
            if not app_prefix:
                logger.warning("No .app bundle found in IPA")
                return result
            result['is_valid'] = True

            info_path = f"{app_prefix}/Info.plist"
            exec_name = app_prefix.split('/')[-1].replace('.app', '')
            if info_path in names:
                with zf.open(info_path) as f:
                    plist = plistlib.load(f)
                result['version'] = plist.get('CFBundleShortVersionString', '0.0.0')
                result['build'] = plist.get('CFBundleVersion', '0')
                result['bundle_id'] = plist.get('CFBundleIdentifier', default_bundle_id)
                result['min_os_version'] = plist.get('MinimumOSVersion')
                exec_name = plist.get('CFBundleExecutable', exec_name)
                for key, value in plist.items():
                    if key.endswith('UsageDescription') and isinstance(value, str) and value.strip():
                        all_privacy[key] = value.strip()

            exec_path = f"{app_prefix}/{exec_name}"
            if exec_path in names:
                with zf.open(exec_path) as f:
                    all_entitlements |= _extract_entitlements_from_macho(f.read())

            appex_prefixes = set()
            for n in names:
                em = re.match(rf'^{re.escape(app_prefix)}/PlugIns/([^/]+\.appex)/', n)
                if em:
                    appex_prefixes.add(f"{app_prefix}/PlugIns/{em.group(1)}")

            for appex in sorted(appex_prefixes):
                ext_info = f"{appex}/Info.plist"
                ext_exec = appex.split('/')[-1].replace('.appex', '')
                if ext_info in names:
                    with zf.open(ext_info) as f:
                        ext_plist = plistlib.load(f)
                    ext_exec = ext_plist.get('CFBundleExecutable', ext_exec)
                    for key, value in ext_plist.items():
                        if key.endswith('UsageDescription') and isinstance(value, str) and value.strip():
                            all_privacy[key] = value.strip()
                ext_exec_path = f"{appex}/{ext_exec}"
                if ext_exec_path in names:
                    with zf.open(ext_exec_path) as f:
                        all_entitlements |= _extract_entitlements_from_macho(f.read())

        result['permissions'] = {
            'entitlements': sorted(all_entitlements),
            'privacy': dict(sorted(all_privacy.items())),
        }

    except Exception as e:
        logger.error(f"Error parsing IPA: {e}")

    return result

def get_ipa_sha256(ipa_path):
    sha256_hash = hashlib.sha256()
    with open(ipa_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def package_app_to_ipa(app_path, output_ipa_path):
    try:
        with zipfile.ZipFile(output_ipa_path, 'w', zipfile.ZIP_DEFLATED) as ipa:
            for root, _, files in os.walk(app_path):
                for file in files:
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, os.path.join(app_path, '..'))
                    ipa.write(full_path, os.path.join('Payload', relative_path))
        return True
    except Exception as e:
        logger.error(f"Failed to package IPA from {app_path}: {e}")
        return False

def repackage_ipa_with_bundle_id(ipa_path, new_bundle_id, output_path=None):
    if output_path is None:
        output_path = ipa_path

    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix='ipa_repackage_')

        with zipfile.ZipFile(ipa_path, 'r') as ipa:
            ipa.extractall(temp_dir)

        payload_dir = os.path.join(temp_dir, 'Payload')
        if not os.path.exists(payload_dir):
            logger.error(f"No Payload directory found in {ipa_path}")
            return False, None

        app_dirs = [d for d in os.listdir(payload_dir) if d.endswith('.app')]
        if not app_dirs:
            logger.error(f"No .app directory found in {ipa_path}")
            return False, None

        app_dir = os.path.join(payload_dir, app_dirs[0])
        info_plist_path = os.path.join(app_dir, 'Info.plist')

        if not os.path.exists(info_plist_path):
            logger.error(f"Info.plist not found in {app_dir}")
            return False, None

        with open(info_plist_path, 'rb') as f:
            plist = plistlib.load(f)

        old_bundle_id = plist.get('CFBundleIdentifier', '')
        plist['CFBundleIdentifier'] = new_bundle_id

        with open(info_plist_path, 'wb') as f:
            plistlib.dump(plist, f)

        logger.info(f"Modified bundle ID: {old_bundle_id} -> {new_bundle_id}")

        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as ipa:
            FIXED_TIME = (2020, 1, 1, 0, 0, 0)
            all_files = []
            for root, dirs, files in os.walk(temp_dir):
                dirs.sort()
                for file in sorted(files):
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, temp_dir)
                    all_files.append((relative_path, full_path))

            for relative_path, full_path in sorted(all_files):
                info = zipfile.ZipInfo(relative_path, date_time=FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full_path, 'rb') as fh:
                    ipa.writestr(info, fh.read())

        sha256 = get_ipa_sha256(output_path)

        return True, sha256

    except Exception as e:
        logger.error(f"Failed to repackage IPA {ipa_path}: {e}")
        return False, None
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

