from fastapi import FastAPI, File, UploadFile, HTTPException, Depends, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from .ocr_processor import extract_text_from_pdf, parse_aadhaar_details, validate_aadhaar
import io
import logging
from typing import Optional
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.security import APIKeyHeader
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from datetime import datetime
import hashlib
import os

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('app.log')
    ]
)
logger = logging.getLogger(__name__)

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)

# Initialize API
app = FastAPI(
    title="Aadhaar OCR API",
    description="API for extracting information from Aadhaar cards using OCR",
    version="1.0.0",
    docs_url=None if os.getenv('ENVIRONMENT') == 'production' else '/docs',
    redoc_url=None if os.getenv('ENVIRONMENT') == 'production' else '/redoc'
)

# Setup rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# No API key authentication required - simplified interface

# Add middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = datetime.utcnow()
    response = await call_next(request)
    process_time = (datetime.utcnow() - start_time).total_seconds() * 1000
    logger.info(
        f"Method: {request.method} Path: {request.url.path} "
        f"Status: {response.status_code} Process Time: {process_time:.2f}ms"
    )
    return response

@app.post("/extract")
@limiter.limit("10/minute")
async def extract_aadhaar_info(
    request: Request,
    file: UploadFile = File(...),
    password: str = Form(...)
):
    if not password or len(password.strip()) == 0:
        raise HTTPException(status_code=400, detail="Password is required for encrypted PDF")

    try:
        # Validate file type and size
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
            
        # 5MB size limit
        file_size = 0
        content = await file.read()
        file_size = len(content)
        if file_size > 5 * 1024 * 1024:  # 5MB in bytes
            raise HTTPException(status_code=400, detail="File size exceeds 5MB limit")
            
        # Generate unique file identifier
        file_hash = hashlib.sha256(content).hexdigest()
        
        # Log request metadata
        logger.info(
            f"Processing request - File: {file.filename}, "
            f"Size: {file_size/1024:.2f}KB, "
            f"Hash: {file_hash}, "
            f"Timestamp: {datetime.utcnow().isoformat()}"
        )

        # File content already read above
        # Reset file pointer for potential future operations
        await file.seek(0)
        
        # Process PDF and extract text
        try:
            text = extract_text_from_pdf(content, password)
        except Exception as e:
            logger.error(f"PDF processing error: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))

        # Parse Aadhaar details
        try:
            aadhaar_data = parse_aadhaar_details(text)
        except Exception as e:
            logger.error(f"Parsing error: {str(e)}")
            raise HTTPException(status_code=500, detail="Error parsing Aadhaar details")

        # Validate Aadhaar number if present
        if aadhaar_data.aadhaar_number:
            clean_aadhaar = aadhaar_data.aadhaar_number.replace(" ", "")
            if not validate_aadhaar(clean_aadhaar):
                logger.warning(f"Invalid Aadhaar number detected")
                return JSONResponse(
                    status_code=200,
                    content={
                        "warning": "Invalid Aadhaar number detected",
                        "data": aadhaar_data.dict()
                    }
                )

        return JSONResponse(
            status_code=200,
            content={"data": aadhaar_data.dict()}
        )

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def root():
    return RedirectResponse(url="/docs")