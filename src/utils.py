"""
utils.py — misc helpers
"""

def is_image_extension(ext: str) -> bool:
    ext = ext.lower().lstrip(".")
    return ext in {
        "png", "jpg", "jpeg", "gif", "webp", "bmp",
        "tif", "tiff", "svg"
    }
