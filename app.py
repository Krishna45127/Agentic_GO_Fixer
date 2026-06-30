from fastapi import BackgroundTasks, FastAPI, HTTPException, Path, Query
from fastapi.responses import JSONResponse
import json
from main import solve_issue
from pydantic import BaseModel, Field
from typing import Annotated, Literal, Optional
from fastapi import BackgroundTasks
import uuid

app = FastAPI()
jobs = {}

class IssueRequest(BaseModel):
    issue: Annotated[str, Field(..., description='GitHub issue text to fix' )]
    repo: Annotated[Optional[str], Field(default=None, description='Path to the cloned Go repo')]
    output: Annotated[Optional[str], Field(default=None, description='Directory for output artefacts')]


def run_job(job_id, issue, repo, output):
    try:
        jobs[job_id]["status"] = "running"

        result = solve_issue(
            issue=issue,
            repo=repo,
            output=output
        )

        jobs[job_id] = {
            "status": "completed",
            "result": result
        }

    except Exception as e:
        jobs[job_id] = {
            "status": "failed",
            "error": str(e)
        }

  
@app.post("/solve")
def solve_request(
    request: IssueRequest,
    background_tasks: BackgroundTasks
):
    try:
        job_id = str(uuid.uuid4())

        jobs[job_id] = {"status": "queued"}
        
        background_tasks.add_task(
            run_job,
            job_id,
            request.issue,
            request.repo,
            request.output
        )


        return {
            "job_id": job_id,
            "status": "queued"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )

    return jobs[job_id]   
