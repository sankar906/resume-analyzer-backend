import json
import logging
import os
import shutil
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.api.v1.api import api_router
from src.db.init_db import init_db
from src.db.manager import db_manager

logger = logging.getLogger(__name__)

try:
    from src.services.extract import extract_router, extract_resume_details
    from src.services.evaluate import evaluate_router, evaluate_extracted_resume
except ImportError:
    extract_router = None
    extract_resume_details = None
    evaluate_router = None
    evaluate_extracted_resume = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        await init_db()
    except Exception:
        logger.exception("startup: database init failed")
        raise
    yield
    try:
        await db_manager.close_pool()
    except Exception:
        logger.exception("shutdown: pool close failed")


# Initialize the central FastAPI application
app = FastAPI(title="SeaHire Resume Evaluation API", lifespan=lifespan)


@app.exception_handler(Exception)
async def unhandled_exception(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    if isinstance(exc, RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": exc.errors()})
    logger.exception("unhandled error")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

# Mount our modular routers from their respective files
app.include_router(api_router, prefix="/api/v1")
if extract_router is not None:
    app.include_router(extract_router, prefix="/api/resume")
if evaluate_router is not None:
    app.include_router(evaluate_router, prefix="/api/resume")


if extract_resume_details is not None and evaluate_extracted_resume is not None:

    @app.post("/api/resume/extract-and-evaluate", tags=["Combined Pipeline"])
    async def api_extract_and_evaluate(file: UploadFile = File(...)):
        """
        Endpoint 3: Chained pipeline. Complete PDF inference -> JSON extraction -> Job evaluation.
        """
        os.makedirs("temp_uploads", exist_ok=True)
        file_id = str(uuid.uuid4())
        temp_path = os.path.join("temp_uploads", f"{file_id}.pdf")
        try:
            with open(temp_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)

            json_output_str = extract_resume_details(temp_path)
            eval_result_str = evaluate_extracted_resume(json_output_str)

            try:
                extracted = json.loads(json_output_str)
                evaluation = json.loads(eval_result_str)
            except json.JSONDecodeError as e:
                raise HTTPException(status_code=500, detail=f"Invalid JSON: {e}") from e
            return {"extracted_data": extracted, "evaluation": evaluation}

        except HTTPException:
            raise
        except Exception as e:
            logger.exception("extract-and-evaluate failed")
            raise HTTPException(status_code=500, detail=str(e)) from e
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8008, reload=True)
