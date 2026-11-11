import uvicorn

from logistic import config
from logistic.app import app  # noqa: F401  (uvicorn main:app)

if __name__ == "__main__":
    uvicorn.run("main:app", host=config.APP_HOST, port=config.APP_PORT)
