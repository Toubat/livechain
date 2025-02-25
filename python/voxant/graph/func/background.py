from pydantic import BaseModel


class BackgroundTask(BaseModel): ...


class BackgroundTaskManager:
    def __init__(self): ...
