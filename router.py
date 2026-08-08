from typing import Dict, Any, List, Optional
from PySide6.QtCore import QObject, Signal

class PySideRouter(QObject):
    route_changed = Signal(dict)

    _instance = None

    def __init__(self):
        super().__init__()
        self.history: List[Dict[str, Any]] = []
        self.current_route: Optional[Dict[str, Any]] = None

    @classmethod
    def get_instance(cls) -> "PySideRouter":
        if cls._instance is None:
            cls._instance = PySideRouter()
        return cls._instance

    def navigate(self, path: str, params: Optional[Dict[str, Any]] = None) -> None:
        if params is None:
            params = {}

        route_state = {"path": path, "params": params}
        if self.current_route:
            self.history.append(self.current_route)

        self.current_route = route_state
        self.route_changed.emit(route_state)

    def back(self) -> bool:
        if self.history:
            previous_route = self.history.pop()
            self.current_route = previous_route
            self.route_changed.emit(previous_route)
            return True
        return False

def get_router() -> PySideRouter:
    return PySideRouter.get_instance()
