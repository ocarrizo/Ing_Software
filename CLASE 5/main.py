from fastapi import FastAPI

app=FastAPI()

@app.get("/")
async def prueba_root():
    return {"message": "Accediste al endpoint de prueba"}

from fastapi import FastAPI

app = FastAPI()

@app.get("/files")
def get_files():
    return {"files": ["osky crack", "osly champion"]}

@app.post("/files")
def create_file(name: str):
    return {"message": f"Archivo {name} creado correctamente"}

@app.get("/files/{file_name}")
def read_file(file_name: str):
    return {"file": file_name, "content": "contenido del archivo..."}
