import os
import shutil

def move_file(src: str, dst: str) -> None:
    """
    Safely move file from src to dst.
    Attempts atomic os.rename first, falling back to copy+unlink for cross-filesystem moves.
    """
    if not os.path.exists(src):
        raise FileNotFoundError(f"Source file does not exist: {src}")
        
    dst_dir = os.path.dirname(dst)
    if dst_dir:
        os.makedirs(dst_dir, exist_ok=True)
        
    try:
        os.rename(src, dst)
    except OSError as err:
        import errno
        # EXDEV is the error code for cross-device link moves
        if err.errno == errno.EXDEV:
            shutil.copy2(src, dst)
            try:
                os.remove(src)
            except OSError as unlink_err:
                print(f"[FileOps] Warning: failed to unlink source after copy: {unlink_err}")
        else:
            raise err
