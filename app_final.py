from fastapi import FastAPI

APP_VERSION={
  "version": "0.1.0"
}

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/version")
def version():
    return APP_VERSION
