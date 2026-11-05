from fastapi import FastAPI

app = FastAPI(title="rooms-app")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
