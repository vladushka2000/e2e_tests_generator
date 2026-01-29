import os

import uvicorn
from fastapi import FastAPI, UploadFile, File, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(prefix="/api")

class ServerRequest(BaseModel):
    """
    Веб-схема запроса на сервер
    """

    message: str


class ServerResponse(BaseModel):
    """
    Веб-схема ответа сервера
    """

    status: int
    message: str


@app.get("/")
async def get_frontend() -> HTMLResponse:
    """
    Получить профессиональный фронтенд
    :return: фронтенд
    """

    with open("static/index.html", "r", encoding="utf-8") as f:
        content = f.read()

    if os.getenv("IS_PROXY"):
        content = content.replace("http://localhost:7777", "http://localhost:8080")

    return HTMLResponse(content=content)


@router.get("/greetings")
async def get_greetings(name: str) -> str:
    """
    Поздороваться с приложением
    :param name: имя
    :return: персональное приветствие
    """

    return f"Привет, {name}! Как дела?)"


@router.post("/echo")
async def get_echo(text: ServerRequest) -> ServerResponse:
    """
    Получить эхо (КАПС)
    :param text: текст
    :return: эхо
    """

    uppercase_text = text.message.upper()
    parts = []

    for i in range(3):
        if i == 0:
            parts.append(uppercase_text)
        else:
            parts.append(uppercase_text[:len(uppercase_text) - i] + "...")

    return ServerResponse(
        status=200,
        message=" → ".join(parts)
    )


@router.get("/farewells")
async def get_farewells() -> ServerResponse:
    """
    Попращаться с приложением
    :return: пока-пока
    """

    return ServerResponse(
        status=200,
        message="Пока-пока"
    )


@router.post("/monologue")
async def get_monologue(
    file: UploadFile = File(None)  # noqa
) -> FileResponse:
    """
    Получить глубокий монолог в обмен на любой файл
    :param file: любой файл
    :return: глубокий монолог
    """

    file_path = "static/test_response.txt"

    return FileResponse(
        path=file_path,
        filename="monologue.txt",
        media_type="text/plain"
    )

app.include_router(router)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=7777,
        reload=True
    )
