import os
import uuid
import requests

from app.config.settings import (
    META_ACCESS_TOKEN
)


def get_media_url(
    media_id: str
):

    url = (
        f"https://graph.facebook.com/v19.0/"
        f"{media_id}"
    )

    headers = {
        "Authorization":
            f"Bearer {META_ACCESS_TOKEN}"
    }

    response = requests.get(
        url,
        headers=headers
    )

    response.raise_for_status()

    return response.json()["url"]


from fastapi import HTTPException

def download_media(
    media_id: str,
    upload_folder: str,
    original_filename: str = None
):
    """
    Download a WhatsApp media file by media_id to upload_folder.
    original_filename is used as a fallback to determine file extension
    when WhatsApp CDN returns an ambiguous Content-Type (e.g. application/octet-stream).
    """
    os.makedirs(
        upload_folder,
        exist_ok=True
    )

    media_url = get_media_url(
        media_id
    )

    headers = {
        "Authorization":
            f"Bearer {META_ACCESS_TOKEN}"
    }

    # Fetch using stream=True to check content length first
    response = requests.get(
        media_url,
        headers=headers,
        stream=True
    )

    response.raise_for_status()

    # Verify content length does not exceed 10 MB
    content_length = response.headers.get("Content-Length")
    if content_length:
        size_bytes = int(content_length)
        if size_bytes > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail=f"Uploaded file size ({round(size_bytes / (1024 * 1024), 2)} MB) exceeds 10 MB limit."
            )

    content_type = response.headers.get(
        "Content-Type",
        ""
    ).lower().split(";")[0].strip()

    extension_map = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/3gpp": ".3gp",
        "video/quicktime": ".mov",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/aac": ".aac",
        "audio/amr": ".amr",
        "text/csv": ".csv",
        "text/plain": ".txt",
        "application/csv": ".csv",
        "application/x-rar-compressed": ".rar",
        "application/vnd.rar": ".rar",
        "application/zip": ".zip",
        "application/msword": ".doc",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/vnd.ms-powerpoint": ".ppt",
        "application/rtf": ".rtf",
    }

    file_extension = extension_map.get(content_type, "")

    # Dynamic fallback: Guess extension from subtype (e.g. application/rtf -> .rtf)
    if not file_extension and "/" in content_type:
        subtype = content_type.split("/")[1].split(";")[0].strip()
        if subtype and len(subtype) <= 5 and subtype.isalnum():
            file_extension = f".{subtype}"
            print(f"[DOWNLOAD_MEDIA] Guessed extension '{file_extension}' from Content-Type '{content_type}'")

    # Fallback: if content-type is ambiguous, derive extension from the original
    # filename supplied by WhatsApp document metadata (e.g. "Quotation.pdf" -> ".pdf").
    if not file_extension and original_filename:
        fallback_ext = os.path.splitext(original_filename)[1].lower()
        if fallback_ext:
            file_extension = fallback_ext
            print(f"[DOWNLOAD_MEDIA] Content-Type '{content_type}' unrecognized; "
                  f"using extension '{file_extension}' from original filename '{original_filename}'")

    # Final fallback if still unknown
    if not file_extension:
        file_extension = ".bin"
        print(f"[DOWNLOAD_MEDIA] WARNING: Could not determine file extension. "
              f"content_type='{content_type}', original_filename='{original_filename}'. Saved as .bin")

    filename = (
        str(uuid.uuid4())
        + file_extension
    )

    file_path = os.path.join(
        upload_folder,
        filename
    )

    # Write in chunks of 8KB to avoid buffering large files entirely in memory
    bytes_downloaded = 0
    with open(
        file_path,
        "wb"
    ) as file:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                bytes_downloaded += len(chunk)
                if bytes_downloaded > 10 * 1024 * 1024:
                    file.close()
                    if os.path.exists(file_path):
                        os.remove(file_path)
                    raise HTTPException(
                        status_code=400,
                        detail="File download exceeded maximum allowed size of 10 MB."
                    )
                file.write(chunk)

    print(f"[DOWNLOAD_MEDIA] Saved: {file_path} ({bytes_downloaded} bytes, type: {content_type})")

    # Convert Windows path separators to URL separators
    return file_path.replace("\\", "/")