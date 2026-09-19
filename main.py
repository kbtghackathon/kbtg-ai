"""
FastAPI Application for Recurring Expense Detection Microservice

This is a stateless microservice that analyzes bank statements and detects
recurring expenses without any database dependencies.
"""

import logging
from typing import List, Optional
from fastapi import FastAPI, HTTPException, status, File, UploadFile, Form
from pydantic import BaseModel, Field
import uvicorn

from src.pipeline.stateless_pipeline import analyze_from_base64
from src.categorizer.categorization_module import CategorizationModule

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="Recurring Expense Detection API",
    description="Stateless microservice for analyzing bank statements and detecting recurring expenses",
    version="1.0.0"
)

# Initialize merchant dictionary on startup
merchant_dict_loaded = False
merchant_count = 0

@app.on_event("startup")
async def startup_event():
    """Load merchant dictionary on startup"""
    global merchant_dict_loaded, merchant_count
    try:
        # Initialize categorizer to load merchant dict
        categorizer = CategorizationModule()
        if CategorizationModule._merchant_dict_cache:
            merchant_count = len(CategorizationModule._merchant_dict_cache)
            merchant_dict_loaded = True
            logger.info(f"Merchant dictionary loaded successfully: {merchant_count} entries")
        else:
            logger.warning("Merchant dictionary is empty")
            merchant_dict_loaded = True
            merchant_count = 0
    except Exception as e:
        logger.error(f"Failed to load merchant dictionary: {e}")
        merchant_dict_loaded = False


# Pydantic models for request/response
class UserLabel(BaseModel):
    """User category label for a recipient"""
    recipient_key: str = Field(..., description="Unique recipient identifier")
    category: str = Field(..., description="Category code (e.g., 'rent', 'internet')")
    category_label_th: str = Field(..., description="Category label in Thai")


class AnalyzeRequest(BaseModel):
    """Request model for /analyze endpoint"""
    statements_pdf_base64: List[str] = Field(
        ...,
        description="List of bank statement PDFs encoded as base64 strings (1-6 statements)",
        min_items=1,
        max_items=6
    )
    current_salary: float = Field(
        ...,
        description="User's current month salary",
        gt=0
    )
    existing_user_labels: List[UserLabel] = Field(
        default_factory=list,
        description="Existing user category labels for recurring expenses"
    )


class RecurringExpenseItem(BaseModel):
    """Single recurring expense item"""
    category: str
    category_label_th: str
    amount: float
    confidence: float
    recipient_key: str


class SampleTransaction(BaseModel):
    """Sample transaction for pending label"""
    date: Optional[str]
    amount: str
    recipient: str


class PendingLabel(BaseModel):
    """Pending user label item"""
    recipient_key: str
    detected_amount: float
    n_months_detected: int
    category_suggestions: List[str]
    sample_transactions: List[SampleTransaction]


class AnalyzeResponse(BaseModel):
    """Response model for /analyze endpoint"""
    salary_this_month: float = Field(..., description="User's current month salary")
    recurring_expenses: List[RecurringExpenseItem] = Field(
        ...,
        description="List of detected recurring expenses"
    )
    total_recurring: float = Field(..., description="Total recurring expenses amount")
    remaining_after_reserve: float = Field(
        ...,
        description="Remaining income after recurring expenses"
    )
    pending_user_labels: List[PendingLabel] = Field(
        ...,
        description="Recurring expenses needing user category labels"
    )
    updated_user_labels: List[UserLabel] = Field(
        ...,
        description="Updated user labels (stateless mode: always empty)"
    )
    data_completeness_warning: Optional[str] = Field(
        None,
        description="Warning message if data is incomplete (< 6 months)"
    )
    data_months_available: int = Field(..., description="Number of months of data analyzed")
    parsed_transaction_count: int = Field(..., description="Total transactions parsed from PDFs")
    parse_success_rate: float = Field(..., description="Parse success rate (0.0-1.0)")


class HealthResponse(BaseModel):
    """Health check response"""
    status: str = Field(..., description="Service status")
    merchant_dict_loaded: bool = Field(..., description="Whether merchant dictionary loaded")
    merchant_count: int = Field(..., description="Number of merchants in dictionary")


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint
    
    Returns service status and merchant dictionary info.
    """
    return HealthResponse(
        status="ok" if merchant_dict_loaded else "degraded",
        merchant_dict_loaded=merchant_dict_loaded,
        merchant_count=merchant_count
    )


@app.post("/analyze", response_model=AnalyzeResponse, tags=["Analysis"])
async def analyze_endpoint(request: AnalyzeRequest):
    """
    Analyze bank statements and detect recurring expenses
    
    This endpoint accepts bank statement PDFs (as base64), analyzes transactions,
    detects recurring patterns, and returns a comprehensive summary.
    
    Args:
        request: Analysis request with PDFs and user data
        
    Returns:
        Complete recurring expense analysis
        
    Raises:
        HTTPException: If analysis fails
    """
    try:
        logger.info(
            f"Received analyze request: {len(request.statements_pdf_base64)} PDFs, "
            f"salary={request.current_salary:.2f}, "
            f"existing_labels={len(request.existing_user_labels)}"
        )
        
        # Convert user labels to dict format
        existing_labels = [
            {
                "recipient_key": label.recipient_key,
                "category": label.category,
                "category_label_th": label.category_label_th
            }
            for label in request.existing_user_labels
        ]
        
        # Call pipeline
        result = analyze_from_base64(
            statements_pdf_base64=request.statements_pdf_base64,
            current_salary=request.current_salary,
            existing_user_labels=existing_labels
        )
        
        logger.info(
            f"Analysis complete: {result['parsed_transaction_count']} transactions, "
            f"{len(result['recurring_expenses'])} recurring expenses, "
            f"total={result['total_recurring']:.2f}"
        )
        
        # Convert result dict to response model
        return AnalyzeResponse(**result)
    
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {str(e)}"
        )



@app.post("/analyze-upload", response_model=AnalyzeResponse, tags=["Analysis"])
async def analyze_upload_endpoint(
    pdf_files: List[UploadFile] = File(..., description="PDF statement files (1-6 files)"),
    current_salary: float = Form(..., description="User's current month salary", gt=0),
    existing_user_labels: Optional[str] = Form(default="[]", description="JSON string of existing user labels")
):
    """
    Analyze bank statements (upload PDF files directly)
    
    Alternative endpoint that accepts PDF files via multipart/form-data instead of base64.
    Backend can upload files directly without encoding.
    
    Args:
        pdf_files: List of PDF files (multipart/form-data)
        current_salary: User's current month salary
        existing_user_labels: JSON string array of user labels
        
    Returns:
        Complete recurring expense analysis
        
    Example usage (curl):
        curl -X POST http://localhost:8000/analyze-upload \
          -F "pdf_files=@statement1.pdf" \
          -F "pdf_files=@statement2.pdf" \
          -F "current_salary=30000.0" \
          -F "existing_user_labels=[]"
    """
    import json
    import base64
    
    try:
        logger.info(
            f"Received analyze-upload request: {len(pdf_files)} PDFs, "
            f"salary={current_salary:.2f}"
        )
        
        # Validate PDF count
        if not (1 <= len(pdf_files) <= 6):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Must provide 1-6 PDF files"
            )
        
        # Validate content types
        for pdf_file in pdf_files:
            if not pdf_file.content_type == "application/pdf":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"File {pdf_file.filename} is not a PDF"
                )
        
        # Read and encode PDFs to base64
        statements_base64 = []
        for pdf_file in pdf_files:
            pdf_bytes = await pdf_file.read()
            pdf_base64 = base64.b64encode(pdf_bytes).decode('utf-8')
            statements_base64.append(pdf_base64)
            logger.info(f"Read PDF: {pdf_file.filename} ({len(pdf_bytes)} bytes)")
        
        # Parse user labels JSON
        try:
            existing_labels = json.loads(existing_user_labels)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="existing_user_labels must be valid JSON array"
            )
        
        # Call pipeline (reuse existing base64 logic)
        result = analyze_from_base64(
            statements_pdf_base64=statements_base64,
            current_salary=current_salary,
            existing_user_labels=existing_labels
        )
        
        logger.info(
            f"Analysis complete: {result['parsed_transaction_count']} transactions, "
            f"{len(result['recurring_expenses'])} recurring expenses"
        )
        
        return AnalyzeResponse(**result)
    
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {str(e)}"
        )



@app.post("/analyze-text", response_model=AnalyzeResponse, tags=["Analysis"])
async def analyze_text_endpoint(
    statement_text: str = Form(..., description="Bank statement text (raw text from PDF)"),
    current_salary: float = Form(..., description="User's current month salary", gt=0),
    existing_user_labels: Optional[str] = Form(default="[]", description="JSON string of existing user labels")
):
    """
    Analyze bank statement from raw text directly
    
    This endpoint accepts statement text directly instead of PDF file.
    Useful for testing or when PDF extraction is problematic.
    
    Args:
        statement_text: Raw statement text (output from PDF copy-paste)
        current_salary: User's current month salary
        existing_user_labels: JSON string array of user labels
        
    Returns:
        Complete recurring expense analysis
    """
    import json
    from src.pipeline.stateless_pipeline import analyze_from_text
    
    try:
        logger.info(f"Received analyze-text request: salary={current_salary:.2f}")
        
        # Parse user labels JSON
        try:
            existing_labels = json.loads(existing_user_labels)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="existing_user_labels must be valid JSON array"
            )
        
        # Call text-based pipeline
        result = analyze_from_text(
            statement_texts=[statement_text],
            current_salary=current_salary,
            existing_user_labels=existing_labels
        )
        
        logger.info(
            f"Analysis complete: {result['parsed_transaction_count']} transactions, "
            f"{len(result['recurring_expenses'])} recurring expenses"
        )
        
        return AnalyzeResponse(**result)
    
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {str(e)}"
        )



@app.post("/analyze-text-upload", response_model=AnalyzeResponse, tags=["Analysis"])
async def analyze_text_upload_endpoint(
    text_file: UploadFile = File(..., description="Text file containing statement text"),
    current_salary: float = Form(..., description="User's current month salary", gt=0),
    existing_user_labels: Optional[str] = Form(default="[]", description="JSON string of existing user labels")
):
    """
    Analyze bank statement from text file upload
    
    Upload a .txt file containing the statement text directly.
    
    Example (curl):
        curl -X POST http://localhost:8000/analyze-text-upload \
          -F "text_file=@statement_text.txt" \
          -F "current_salary=30000.0" \
          -F "existing_user_labels=[]"
    """
    import json
    from src.pipeline.stateless_pipeline import analyze_from_text
    
    try:
        # Read text file
        text_content = await text_file.read()
        statement_text = text_content.decode('utf-8')
        
        logger.info(f"Received text file: {text_file.filename} ({len(text_content)} bytes)")
        
        # Parse user labels
        try:
            existing_labels = json.loads(existing_user_labels)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="existing_user_labels must be valid JSON array"
            )
        
        # Call pipeline
        result = analyze_from_text(
            statement_texts=[statement_text],
            current_salary=current_salary,
            existing_user_labels=existing_labels
        )
        
        logger.info(f"Analysis complete: {result['parsed_transaction_count']} transactions")
        
        return AnalyzeResponse(**result)
    
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Text file must be UTF-8 encoded"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis failed: {str(e)}"
        )

@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "service": "Recurring Expense Detection API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs"
    }


if __name__ == "__main__":
    # Run the application
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level="info"
    )


