from fastapi import FastAPI

app = FastAPI(title="PaperAssist System")


@app.get("/api/v1/health")
def health():
    return {
        "status": "ok",
        "service": "paperassist-system",
    }
