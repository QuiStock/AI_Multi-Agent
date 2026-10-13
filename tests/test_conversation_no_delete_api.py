from src.main import create_app


def test_conversation_delete_is_not_exposed() -> None:
    routes = {
        (method, route.path)
        for route in create_app().routes
        for method in getattr(route, "methods", ())
    }

    assert ("DELETE", "/api/v1/conversations/{conversation_id}") not in routes
