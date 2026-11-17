import json
from pathlib import Path

import c2pa

from cineforge.schemas.bible import EntityBible


def sign_c2pa_manifest(
    input_mp4: Path,
    output_mp4: Path,
    bible: EntityBible,
    cert_path: str = "",
    key_path: str = "",
    require_signed: bool = False,
) -> tuple[Path, bool]:
    manifest_def = {
        "claim_generator": "CineForge-Agent/0.1.7",
        "title": bible.title,
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {
                    "actions": [
                        {
                            "action": "c2pa.created",
                            "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
                        }
                    ]
                },
            }
        ],
    }
    has_certs = bool(cert_path and key_path and Path(cert_path).exists() and Path(key_path).exists())
    if require_signed and not has_certs:
        raise FileNotFoundError("C2PA cryptographic signing required, but C2PA_CERT_PATH / C2PA_KEY_PATH are missing.")

    if has_certs:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        cert_pem = Path(cert_path).read_bytes()
        key_pem = Path(key_path).read_bytes()
        pk = serialization.load_pem_private_key(key_pem, password=None)
        if not isinstance(pk, ec.EllipticCurvePrivateKey):
            raise TypeError("C2PA ES256 signing requires an EllipticCurvePrivateKey.")
        signer = c2pa.Signer.from_callback(
            lambda d: pk.sign(d, ec.ECDSA(hashes.SHA256())),
            c2pa.C2paSigningAlg.ES256,
            cert_pem,
            "http://timestamp.digicert.com",
        )
        c2pa.Builder(json.dumps(manifest_def)).sign_file(str(input_mp4), str(output_mp4), signer)
        return output_mp4, True

    output_mp4.write_bytes(input_mp4.read_bytes())
    unsigned_meta = {
        "status": "unsigned_sidecar_metadata",
        "warning": "Not cryptographically signed. Configure C2PA_CERT_PATH and C2PA_KEY_PATH for embedded X.509 C2PA signing.",
        "manifest": manifest_def,
    }
    output_mp4.with_suffix(".unsigned_c2pa.json").write_text(json.dumps(unsigned_meta, indent=2))
    return output_mp4, False
