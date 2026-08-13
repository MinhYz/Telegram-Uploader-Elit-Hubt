import hashlib
import aiohttp
from pathlib import Path
from utils.logger import logger

class StreamIO:
    """Stream Downloader & Chunked Uploader with Checksum Verification."""

    @staticmethod
    async def download_file_stream(url: str, save_path: Path, cookies: dict = None, chunk_size: int = 65536) -> tuple[bool, str]:
        """Stream download file directly to disk to prevent RAM buffer overflow."""
        try:
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return False, f"HTTP Error {response.status}"
                    
                    md5 = hashlib.md5()
                    sha256 = hashlib.sha256()
                    
                    with open(save_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(chunk_size):
                            f.write(chunk)
                            md5.update(chunk)
                            sha256.update(chunk)

                    logger.debug(f"Stream downloaded {save_path.name} (MD5: {md5.hexdigest()[:8]})")
                    return True, md5.hexdigest()
        except Exception as e:
            logger.error(f"Failed stream download for {url}: {e}")
            return False, str(e)

    @staticmethod
    def calculate_checksum(file_path: Path) -> dict:
        """Calculate MD5 and SHA256 checksums of local file."""
        md5 = hashlib.md5()
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                md5.update(chunk)
                sha256.update(chunk)
        return {"md5": md5.hexdigest(), "sha256": sha256.hexdigest()}
