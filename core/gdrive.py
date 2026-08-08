import os
import json
from typing import Dict, Any, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from core.database import backup_dir_for, get_db_path
from core.logger import add_log

SCOPES = ["https://www.googleapis.com/auth/drive.file"]

def get_drive_service(service_account_json_str: str):
    info = json.loads(service_account_json_str)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)

def test_gdrive_connection(service_account_json_str: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    try:
        service = get_drive_service(service_account_json_str)
        if folder_id:
            res = service.files().get(fileId=folder_id, fields="id, name").execute()
            add_log("info", f"Verified Google Drive target folder: {res.get('name')}")
        else:
            res = service.about().get(fields="user").execute()
            add_log("info", f"Verified Google Drive connection for user: {res.get('user', {}).get('displayName')}")
        return {"success": True}
    except Exception as e:
        add_log("error", f"Google Drive connection test failed: {e}")
        return {"success": False, "error": str(e)}

def backup_to_gdrive(drive_path: str, service_account_json_str: str, folder_id: Optional[str] = None) -> Dict[str, Any]:
    db_path = get_db_path(drive_path)
    backup_dir = backup_dir_for(db_path)
    
    if not os.path.exists(backup_dir):
        return {"success": False, "error": "No local snapshot backups created yet."}
        
    try:
        service = get_drive_service(service_account_json_str)
        backups = sorted([
            f for f in os.listdir(backup_dir)
            if f.startswith("media_library-") and f.endswith(".db")
        ], reverse=True)
        
        if not backups:
            return {"success": False, "error": "No backup files available in .backups directory."}
            
        results = []
        for filename in backups[:2]:
            full_p = os.path.join(backup_dir, filename)
            
            q = f"name = '{filename}' and trashed = false"
            if folder_id:
                q += f" and '{folder_id}' in parents"
                
            query_res = service.files().list(q=q, fields="files(id, name)").execute()
            existing_files = query_res.get("files", [])
            
            media = MediaFileUpload(full_p, mimetype="application/x-sqlite3", resumable=True)
            
            if existing_files:
                file_id = existing_files[0]["id"]
                updated = service.files().update(fileId=file_id, media_body=media).execute()
                add_log("info", f"Updated cloud backup snapshot: {filename}", updated.get("id"))
                results.append({"filename": filename, "fileId": updated.get("id"), "action": "updated", "success": True})
            else:
                meta = {"name": filename}
                if folder_id:
                    meta["parents"] = [folder_id]
                created = service.files().create(body=meta, media_body=media, fields="id").execute()
                add_log("info", f"Uploaded new cloud backup snapshot: {filename}", created.get("id"))
                results.append({"filename": filename, "fileId": created.get("id"), "action": "created", "success": True})
                
        return {"success": True, "uploadResults": results}
    except Exception as e:
        add_log("error", f"Cloud backup to Google Drive failed: {e}")
        return {"success": False, "error": str(e)}
