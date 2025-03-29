import pytesseract
from PIL import Image
import cv2
import numpy as np
from typing import List
import PyPDF2
from pdf2image import convert_from_path
import tempfile
import re
from pydantic import BaseModel
import fitz
import io

class AadhaarData(BaseModel):
    aadhaar_number: str = ""
    name_tamil: str = ""
    name: str = ""
    guardian_name: str = ""
    dob: str = ""
    gender: str = ""
    address: str = ""
    district: str = ""
    state: str = ""
    pincode: str = ""
    phone: str = ""
    vid: str = ""

def preprocess_image(image: Image.Image) -> np.ndarray:
    """Preprocesses the image for better OCR performance."""
    image_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(image_cv, cv2.COLOR_BGR2GRAY)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    denoised = cv2.medianBlur(thresh, 3)
    kernel = np.ones((1, 1), np.uint8)
    dilated = cv2.dilate(denoised, kernel, iterations=1)
    return dilated

def extract_text_from_image(image: Image.Image) -> str:
    """Extracts text from the input image using Tesseract OCR."""
    preprocessed = preprocess_image(image)
    custom_config = r'--oem 3 --psm 6 -l eng+tam'
    try:
        text = pytesseract.image_to_string(preprocessed, config=custom_config)
        return text
    except Exception as e:
        raise Exception(f"OCR processing failed: {str(e)}")

def extract_text_from_images(images: List[Image.Image]) -> str:
    """Extracts text from multiple images and combines the results."""
    extracted_text = ""
    for image in images:
        text = extract_text_from_image(image)
        extracted_text += text + "\n"
    return extracted_text

def decrypt_pdf(pdf_path: str, password: str) -> str:
    """Decrypts a password-protected PDF file."""
    decrypted_pdf_path = tempfile.mktemp(suffix=".pdf")
    with open(pdf_path, "rb") as f:
        pdf_reader = PyPDF2.PdfReader(f)
        if pdf_reader.is_encrypted:
            try:
                pdf_reader.decrypt(password)
            except Exception:
                raise Exception("Invalid password provided for the PDF")
        pdf_writer = PyPDF2.PdfWriter()
        for page in pdf_reader.pages:
            pdf_writer.add_page(page)
        with open(decrypted_pdf_path, "wb") as f_out:
            pdf_writer.write(f_out)
    return decrypted_pdf_path

def convert_pdf_to_images(pdf_path: str) -> List[Image.Image]:
    """Converts PDF file into a list of images."""
    try:
        images = convert_from_path(pdf_path, poppler_path=r"C:\Program Files\poppler-24.08.0\Library\bin")
        return images
    except Exception as e:
        raise Exception(f"PDF conversion failed: {str(e)}")

def extract_text_from_pdf(pdf_bytes: bytes, password: str = None) -> str:
    """Extracts text from PDF bytes."""
    if not pdf_bytes:
        raise Exception("Empty PDF stream provided")
    
    text = ""
    doc = None
    try:
        # Validate PDF stream
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            raise Exception(f"Invalid PDF format: {str(e)}")

        # Handle encrypted PDF
        if doc.needs_pass:
            if not password:
                raise Exception("Password required for encrypted PDF")
            try:
                if not doc.authenticate(password):
                    raise Exception("Invalid password provided for PDF")
            except Exception as e:
                raise Exception(f"PDF decryption failed: {str(e)}")
        elif password:
            raise Exception("PDF is not encrypted, password not required")

            if not doc.authenticate(password):
                raise Exception("Invalid password provided for PDF")

        # Extract text from all pages
        for page in doc:
            try:
                page_text = page.get_text("text")
                text += page_text
            except Exception as e:
                raise Exception(f"Error extracting text from page {page.number + 1}: {str(e)}")

        # Validate extracted text
        if not text.strip():
            raise Exception("No text could be extracted from the PDF")

        return text

    except Exception as e:
        if isinstance(e, Exception) and str(e).startswith(("Password required", "Invalid password", "No text could be")):
            raise e
        raise Exception(f"Failed to process PDF: {str(e)}")

    finally:
        if doc:
            try:
                doc.close()
            except:
                pass

def extract_name_from_text(lines: List[str]) -> str:
    """Extracts name from text lines."""
    unwanted_phrases = [
        "Digitally signed by DS Unique",
        "Identification Authority of India",
        "Government of India",
        "Signature Not Verified",
    ]
    for line in lines:
        clean_line = line.strip()
        if (
            re.match(r'^[A-Za-z\s\'-]+$', clean_line)
            and len(clean_line.split()) > 1
            and all(phrase.lower() not in clean_line.lower() for phrase in unwanted_phrases)
        ):
            name_part = re.split(r'\s*(?:S/O|C/O|W/O|D/O)\s*', clean_line, flags=re.IGNORECASE)[0]
            name_part = re.sub(r'\s+[CWSD]\s*$', '', name_part).strip()
            name_part = re.sub(r'\s+', ' ', name_part)
            return name_part
    return ""

def parse_aadhaar_details(text: str) -> AadhaarData:
    """Parses Aadhaar card details from extracted text."""
    data = AadhaarData()
    lines = [line.strip() for line in text.split("\n") if line.strip()]

    # Extract Aadhaar Number
    aadhaar_match = re.search(r'\b(\d{4}\s\d{4}\s\d{4})\b', text)
    if aadhaar_match:
        aadhaar_number = aadhaar_match.group(1)
        # Only validate if number is found
        if validate_aadhaar(aadhaar_number.replace(" ", "")):
            data.aadhaar_number = aadhaar_number
        else:
            # Still store the number even if validation fails
            data.aadhaar_number = aadhaar_number
    
    # Extract VID
    vid_match = re.search(r'VID[:\s]*(\d{4}\s\d{4}\s\d{4}\s\d{4})', text)
    if vid_match:
        data.vid = vid_match.group(1)

    # Extract Name
    tamil_name_match = re.search(r'([\u0B80-\u0BFF\s]+)\n([A-Za-z\s\'-]+)', text)
    if tamil_name_match:
        data.name_tamil = tamil_name_match.group(1).strip()
        data.name = tamil_name_match.group(2).strip().replace("\n", " ")
        data.name = re.split(r'\s*(?:S/O|C/O|W/O|D/O)\s*', data.name, flags=re.IGNORECASE)[0].strip()
        data.name = re.sub(r'\s+[CWSD]\s*$', '', data.name).strip()
        data.name = re.sub(r'\s+', ' ', data.name)
    
    if not data.name:
        data.name = extract_name_from_text(lines)

    # Extract Guardian Name
    guardian_match = re.search(r'(S/o|C/o|D/o|W/o)[.:]?\s*([A-Za-z\s\'-]+)', text, re.IGNORECASE)
    if guardian_match:
        data.guardian_name = guardian_match.group(2).strip()

    # Extract DOB
    dob_match = re.search(r'(DOB|Date of Birth|D\\.O\\.B)[:\s]*?(\d{1,2}[-/]\d{1,2}[-/]\d{4})', text, re.IGNORECASE)
    if dob_match:
        data.dob = dob_match.group(2).replace('-', '/')

    # Extract Gender
    gender_match = re.search(r'\b(Male|Female|Transgender|M|F|T)\b', text, re.IGNORECASE)
    if gender_match:
        data.gender = gender_match.group(1).capitalize()

    # Extract Address
    address_match = re.search(r'(?i)address[:\s]*(.*?)(?=\nDistrict|\nState|\n\d{6}|\nVID|\nDigitally|$)', text, re.DOTALL)
    if address_match:
        address_text = re.sub(r'(S/o|C/o|D/o|W/o)[.:]?\s*[A-Za-z\s\'-]+', '', address_match.group(1).strip(), flags=re.IGNORECASE)
        address_text = re.sub(r'\b\d{4}\s\d{4}\s\d{4}\b', '', address_text)
        address_text = re.sub(r'PO:.*?,', '', address_text)
        address_text = re.sub(r'(?i)\b(dist|state)\b.*', '', address_text)
        address_text = re.sub(r'\n+', ' ', address_text).strip()
        address_text = re.sub(r'\s+', ' ', address_text).strip()
        data.address = address_text

    # Extract District
    district_match = re.search(r'District[:\s]*(.*)', text, re.IGNORECASE)
    if district_match:
        data.district = district_match.group(1).strip().replace(',', '')
    
    # Extract State
    state_match = re.search(r'State[:\s]*(.*)', text, re.IGNORECASE)
    if state_match:
        data.state = state_match.group(1).strip().rstrip(',') 

    # Extract Pincode
    pincode_match = re.search(r'\b(\d{6})\b', text)
    if pincode_match:
        data.pincode = pincode_match.group(1)

    # Extract Phone Number
    phone_match = re.search(r'\b(\d{10})\b', text)
    if phone_match:
        data.phone = phone_match.group(1)

    return data

def validate_aadhaar(aadhaar_number: str) -> bool:
    """Basic validation of Aadhaar number format.
    Returns True if the number meets basic format requirements.
    """
    # Remove any spaces from the number
    aadhaar_number = aadhaar_number.replace(" ", "")
    
    # Basic format validation - just check if it's a 12-digit number
    return bool(aadhaar_number and aadhaar_number.isdigit() and len(aadhaar_number) == 12)