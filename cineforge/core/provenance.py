import json
from pathlib import Path
import c2pa
from cineforge.schemas.bible import EntityBible

def sign_c2pa_manifest(input_mp4: Path, output_mp4: Path, bible: EntityBible, cert_path: str = "", key_path: str = "") -> Path:
    manifest_def = {"claim_generator": "CineForge-Agent/0.1.0", "title": bible.title, "assertions": [{"label": "c2pa.actions", "data": {"actions": [{"action": "c2pa.created", "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"}]}}]}
    if cert_path and key_path and Path(cert_path).exists() and Path(key_path).exists():
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        cert_pem, key_pem = Path(cert_path).read_bytes(), Path(key_path).read_bytes()
        pk = serialization.load_pem_private_key(key_pem, password=None)
        signer = c2pa.create_signer(lambda d: pk.sign(d, ec.ECDSA(hashes.SHA256())), c2pa.SigningAlg.ES256, cert_pem, "http://timestamp.digicert.com")
        c2pa.Builder(json.dumps(manifest_def)).sign_file(str(input_mp4), str(output_mp4), signer)
    else:
        output_mp4.write_bytes(input_mp4.read_bytes())
        output_mp4.with_suffix(".c2pa.json").write_text(json.dumps(manifest_def, indent=2))
    return output_mp4
