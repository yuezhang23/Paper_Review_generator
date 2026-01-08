"""
External file upload and management functions
"""

import uuid
from typing import List
from fastapi import UploadFile, File as FastAPIFile, HTTPException
from utils import file_storage
from content_extraction import extract_text_from_file


async def upload_files(files: List[UploadFile] = FastAPIFile(...)):
    """Upload files and extract text content"""
    try:
        file_ids = []
        for file in files:
            # Read file content
            content = await file.read()
            
            # Generate unique file ID
            file_id = str(uuid.uuid4())
            
            # Extract text based on file type
            text_content = extract_text_from_file(content, file.filename)
            
            # Store file metadata and content
            file_storage[file_id] = {
                "filename": file.filename,
                "content_type": file.content_type,
                "size": len(content),
                "text_content": text_content,
                "file_id": file_id
            }
            
            file_ids.append(file_id)
        
        return {
            "file_ids": file_ids,
            "count": len(file_ids),
            "message": f"Successfully uploaded {len(file_ids)} file(s)"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading files: {str(e)}")
