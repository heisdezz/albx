import json
import os
import subprocess
import psutil
from typing import List, Dict, Any, Optional

user_mounted_drives: List[Dict[str, Any]] = []

def format_size(bytes_size: int) -> str:
    gb = bytes_size / (1024 * 1024 * 1024)
    if gb >= 1000:
        return f"{gb / 1024:.1f} TB"
    return f"{round(gb)} GB"

def is_system_partition(child: dict) -> bool:
    fstype = (child.get("fstype") or "").lower()
    mountpoint = child.get("mountpoint") or ""
    size_bytes = int(child.get("size") or 0)
    label = (child.get("label") or "").lower()

    if fstype in {"swap", "squashfs", "tmpfs", "devtmpfs"}:
        return True

    SKIP_MOUNTS = {"/", "/boot", "/boot/efi", "[SWAP]"}
    if mountpoint in SKIP_MOUNTS:
        return True
        
    if mountpoint and (
        mountpoint.startswith("/sys") or 
        mountpoint.startswith("/dev") or 
        mountpoint.startswith("/proc") or 
        (mountpoint.startswith("/run") and not mountpoint.startswith("/run/media/"))
    ):
        return True

    if size_bytes < 1_073_741_824: # 1 GB
        return True

    if "vtoyefi" in label or "efi" in label or "recovery" in label or "msr" in label:
        return True

    return False

def get_connected_drives() -> List[Dict[str, Any]]:
    drives = []
    
    try:
        cmd = ["lsblk", "-b", "--json", "-o", "NAME,FSTYPE,LABEL,MOUNTPOINT,SIZE,MODEL,TRAN"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        blockdevices = data.get("blockdevices", [])
        
        for dev in blockdevices:
            name = dev.get("name") or ""
            if name.startswith("loop") or name == "zram0":
                continue
                
            model = (dev.get("model") or "").strip()
            tran = (dev.get("tran") or "").strip()
            drive_type = "external" if tran.lower() == "usb" else "internal"
            
            children = dev.get("children", [])
            if not children:
                if is_system_partition(dev):
                    continue
                
                mountpoint = dev.get("mountpoint")
                size_val = int(dev.get("size") or 0)
                is_mounted = bool(mountpoint)
                used_pct = 0
                
                if is_mounted and mountpoint:
                    try:
                        used_pct = round(psutil.disk_usage(mountpoint).percent)
                    except Exception:
                        pass
                
                fstype = (dev.get("fstype") or "").strip() or "unknown"
                label = (dev.get("label") or "").strip() or model or name
                drives.append({
                    "id": f"/dev/{name}",
                    "device": f"/dev/{name}",
                    "name": label,
                    "label": label,
                    "type": drive_type,
                    "fstype": fstype,
                    "size": format_size(size_val),
                    "usedPercentage": used_pct,
                    "status": "mounted" if is_mounted else "unmounted",
                    "is_mounted": is_mounted,
                    "path": mountpoint or ""
                })
                continue
                
            for child in children:
                child_name = child.get("name") or ""
                if is_system_partition(child):
                    continue
                    
                mountpoint = child.get("mountpoint")
                size_val = int(child.get("size") or 0)
                is_mounted = bool(mountpoint)
                used_pct = 0
                
                if is_mounted and mountpoint:
                    try:
                        used_pct = round(psutil.disk_usage(mountpoint).percent)
                    except Exception:
                        pass
                
                fstype = (child.get("fstype") or dev.get("fstype") or "").strip() or "unknown"
                child_label = (child.get("label") or "").strip() or model or child_name
                drives.append({
                    "id": f"/dev/{child_name}",
                    "device": f"/dev/{child_name}",
                    "name": child_label,
                    "label": child_label,
                    "type": drive_type,
                    "fstype": fstype,
                    "size": format_size(size_val),
                    "usedPercentage": used_pct,
                    "status": "mounted" if is_mounted else "unmounted",
                    "is_mounted": is_mounted,
                    "path": mountpoint or ""
                })
                
    except Exception as e:
        print(f"[Drives] Failed to scan drives: {e}")
        
    return drives + user_mounted_drives

def mount_block_device(device_id: str) -> Dict[str, Any]:
    print(f"[Drives] Attempting to mount partition {device_id} via udisksctl")
    try:
        cmd = ["udisksctl", "mount", "-b", device_id]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        
        if result.returncode == 0:
            for drv in get_connected_drives():
                if drv["id"] == device_id and drv["path"]:
                    return {"success": True, "mountPath": drv["path"]}
            
            if "at " in stdout:
                mount_path = stdout.split("at ")[-1].strip()
                return {"success": True, "mountPath": mount_path}
                
            return {"success": True, "mountPath": ""}
        else:
            return {"success": False, "error": stderr or "udisksctl returned non-zero code"}
            
    except Exception as err:
        print(f"[Drives] Mount command failed: {err}")
        return {"success": False, "error": str(err)}

def unmount_block_device(device_id: str) -> Dict[str, Any]:
    print(f"[Drives] Attempting to unmount partition {device_id} via udisksctl")
    try:
        cmd = ["udisksctl", "unmount", "-b", device_id]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            return {"success": True}
        else:
            return {"success": False, "error": result.stderr.strip() or "udisksctl unmount failed"}
    except Exception as err:
        print(f"[Drives] Unmount command failed: {err}")
        return {"success": False, "error": str(err)}
