"""
Example: How to pass PDFs to Gemini models via AI Builder API
This is an experimental approach - may not work if AI Builder API doesn't support it
"""
from typing import Optional, List
from google import genai
from google.genai import types
import httpx
import os
from dotenv import load_dotenv
import pathlib

load_dotenv()

ai_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

async def paper_summary_with_pdf_url(
    doc_url: str,
    model: str = "gemini-2.5-pro"
):
    """
    Attempt to pass PDF directly to Gemini via multimodal content.
    This may not work if AI Builder API doesn't support PDFs in multimodal format.
    """
    
    # Retrieve and encode the PDF byte
    doc_data = httpx.get(doc_url).content

    prompt = "Summarize this document"
    response = ai_client.models.generate_content(
    model=model,
    contents=[
        types.Part.from_bytes(
            data=doc_data,
            mime_type='application/pdf',
        ),
        prompt])
    print(response.text)


    async def paper_summary_with_pdf_upload(
        filepath: str,
        model: str = "gemini-2.5-pro"
    ):
        """
        Attempt to pass PDF directly to Gemini via upload.
        This may not work if AI Builder API doesn't support PDFs in upload format.
        """
        # Retrieve and encode the PDF byte
        filepath = pathlib.Path(filepath)

        prompt = "Summarize this document"
        response = ai_client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(
                data=filepath.read_bytes(),
                mime_type='application/pdf',
            ),
            prompt])
        print(response.text)
        