from typing import Callable, Dict, Any, List, Optional

class Router:
    _instance = None

    def __init__(self):
        self.routes: Dict[str, Callable] = {}
        self.history: List[Dict[str, Any]] = []
        self.current_route: Optional[Dict[str, Any]] = None
        self.listeners: List[Callable[[Dict[str, Any]], None]] = []

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = Router()
        return cls._instance

    def register(self, path: str, factory: Callable) -> None:
        self.routes[path] = factory

    def subscribe(self, listener: Callable[[Dict[str, Any]], None]) -> None:
        self.listeners.append(listener)

    def navigate(self, path: str, params: Optional[Dict[str, Any]] = None) -> None:
        if params is None:
            params = {}
            
        route_state = {"path": path, "params": params}
        if self.current_route:
            self.history.append(self.current_route)
            
        self.current_route = route_state
        self._notify(route_state)

    def back(self) -> bool:
        if self.history:
            previous_route = self.history.pop()
            self.current_route = previous_route
            self._notify(previous_route)
            return True
        return False

    def _notify(self, route_state: Dict[str, Any]) -> None:
        for listener in self.listeners:
            try:
                listener(route_state)
            except Exception as e:
                print(f"[Router] Error notifying listener for route {route_state['path']}: {e}")

def get_router() -> Router:
    return Router.get_instance()
