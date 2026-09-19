"""
PDF Text Extraction Module

This module provides functionality to extract text from K PLUS bank statement PDFs
using pdfplumber library while preserving layout and column structure.

Component 1: PDF Text Extractor
Requirements: 1.1-1.5
"""

from typing import List
from pathlib import Path
import logging
import pdfplumber

logger = logging.getLogger(__name__)


class PDFExtractionError(Exception):
    """Exception raised when PDF extraction fails"""
    pass


class PDFTextExtractor:
    """Extract text from K PLUS bank statement PDFs"""
    
    def extract_text_from_pdf(self, pdf_path: Path) -> str:
        """
        Extract raw text from PDF using pdfplumber
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Raw text content with preserved layout
            
        Raises:
            PDFExtractionError: If PDF cannot be read or is corrupted
            
        Requirements:
            - 1.1: Extract complete text content preserving layout structure
            - 1.2: Return descriptive error message for corrupted/unreadable PDFs
            - 1.4: Use pdfplumber library for text extraction
            - 1.5: Return raw text with preserved whitespace and line breaks
        """
        if not pdf_path.exists():
            error_msg = f"PDF file not found: {pdf_path}"
            logger.error(error_msg)
            raise PDFExtractionError(error_msg)
        
        if not pdf_path.is_file():
            error_msg = f"Path is not a file: {pdf_path}"
            logger.error(error_msg)
            raise PDFExtractionError(error_msg)
        
        if pdf_path.suffix.lower() != '.pdf':
            error_msg = f"File is not a PDF: {pdf_path}"
            logger.error(error_msg)
            raise PDFExtractionError(error_msg)
        
        try:
            # Extract text from all pages while preserving layout
            extracted_text = []
            
            with pdfplumber.open(pdf_path) as pdf:
                # Check if PDF has pages
                if not pdf.pages:
                    error_msg = f"PDF file is empty (no pages): {pdf_path}"
                    logger.error(error_msg)
                    raise PDFExtractionError(error_msg)
                
                for page_num, page in enumerate(pdf.pages, start=1):
                    try:
                        # Extract text with layout preservation
                        # layout=True maintains spatial positioning and column alignment
                        page_text = page.extract_text(layout=True)
                        
                        if page_text:
                            extracted_text.append(page_text)
                            logger.debug(f"Extracted text from page {page_num} of {pdf_path}")
                        else:
                            logger.warning(f"No text found on page {page_num} of {pdf_path}")
                    
                    except Exception as e:
                        logger.error(f"Error extracting text from page {page_num} of {pdf_path}: {e}")
                        raise PDFExtractionError(
                            f"Failed to extract text from page {page_num} of {pdf_path.name}: {str(e)}"
                        )
            
            if not extracted_text:
                error_msg = f"No text could be extracted from PDF: {pdf_path}"
                logger.error(error_msg)
                raise PDFExtractionError(error_msg)
            
            # Join pages with double newline separator
            full_text = "\n\n".join(extracted_text)
            
            logger.info(f"Successfully extracted {len(extracted_text)} pages from {pdf_path}")
            return full_text
        
        except pdfplumber.pdfminer.pdfparser.PDFSyntaxError as e:
            error_msg = f"PDF file is corrupted or invalid: {pdf_path.name} - {str(e)}"
            logger.error(error_msg)
            raise PDFExtractionError(error_msg)
        
        except pdfplumber.pdfminer.pdfdocument.PDFEncryptionError as e:
            error_msg = f"PDF file is password-protected: {pdf_path.name} - {str(e)}"
            logger.error(error_msg)
            raise PDFExtractionError(error_msg)
        
        except PDFExtractionError:
            # Re-raise our custom exceptions
            raise
        
        except Exception as e:
            error_msg = f"Unexpected error reading PDF {pdf_path.name}: {str(e)}"
            logger.error(error_msg)
            raise PDFExtractionError(error_msg)
    
    def extract_text_from_multiple_pdfs(self, pdf_paths: List[Path]) -> List[str]:
        """
        Extract text from multiple PDF files (6 months statements)
        
        Args:
            pdf_paths: List of paths to PDF files
            
        Returns:
            List of raw text content, one per file
            
        Raises:
            PDFExtractionError: If any PDF cannot be read or is corrupted
            
        Requirements:
            - 1.3: Process multiple PDF files (up to 6 months)
        """
        if not pdf_paths:
            logger.warning("No PDF paths provided for extraction")
            return []
        
        logger.info(f"Starting batch extraction for {len(pdf_paths)} PDF files")
        
        extracted_texts = []
        for i, pdf_path in enumerate(pdf_paths, start=1):
            try:
                logger.info(f"Processing PDF {i}/{len(pdf_paths)}: {pdf_path.name}")
                text = self.extract_text_from_pdf(pdf_path)
                extracted_texts.append(text)
            
            except PDFExtractionError as e:
                # Log error and re-raise to stop processing
                logger.error(f"Failed to extract PDF {i}/{len(pdf_paths)}: {e}")
                raise
        
        logger.info(f"Successfully extracted text from all {len(pdf_paths)} PDF files")
        return extracted_texts

    def extract_text_from_pdf_bytes(self, pdf_bytes: bytes) -> str:
        """
        Extract raw text from PDF bytes (for API/microservice use)
        
        Args:
            pdf_bytes: PDF file content as bytes
            
        Returns:
            Raw text content with preserved layout
            
        Raises:
            PDFExtractionError: If PDF cannot be read or is corrupted
        """
        from io import BytesIO
        
        try:
            # Extract text from all pages while preserving layout
            extracted_text = []
            
            with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
                # Check if PDF has pages
                if not pdf.pages:
                    error_msg = "PDF file is empty (no pages)"
                    logger.error(error_msg)
                    raise PDFExtractionError(error_msg)
                
                for page_num, page in enumerate(pdf.pages, start=1):
                    try:
                        # Extract text with layout preservation
                        page_text = page.extract_text(layout=True)
                        
                        if page_text:
                            extracted_text.append(page_text)
                            logger.debug(f"Extracted text from page {page_num}")
                        else:
                            logger.warning(f"No text found on page {page_num}")
                    
                    except Exception as e:
                        logger.error(f"Error extracting text from page {page_num}: {e}")
                        raise PDFExtractionError(
                            f"Failed to extract text from page {page_num}: {str(e)}"
                        )
            
            if not extracted_text:
                error_msg = "No text could be extracted from PDF"
                logger.error(error_msg)
                raise PDFExtractionError(error_msg)
            
            # Join pages with double newline separator
            full_text = "\n\n".join(extracted_text)
            
            logger.info(f"Successfully extracted {len(extracted_text)} pages from PDF bytes")
            return full_text
        
        except pdfplumber.pdfminer.pdfparser.PDFSyntaxError as e:
            error_msg = f"PDF file is corrupted or invalid: {str(e)}"
            logger.error(error_msg)
            raise PDFExtractionError(error_msg)
        
        except pdfplumber.pdfminer.pdfdocument.PDFEncryptionError as e:
            error_msg = f"PDF file is password-protected: {str(e)}"
            logger.error(error_msg)
            raise PDFExtractionError(error_msg)
        
        except PDFExtractionError:
            # Re-raise our custom exceptions
            raise
        
        except Exception as e:
            error_msg = f"Unexpected error reading PDF: {str(e)}"
            logger.error(error_msg)
            raise PDFExtractionError(error_msg)
