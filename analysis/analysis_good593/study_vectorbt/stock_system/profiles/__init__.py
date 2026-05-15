from . import base, neutral, aggressive

_REGISTRY = {"neutral": neutral, "aggressive": aggressive}


def get_profile(name: str):
    if name not in _REGISTRY:
        raise ValueError(f"Unknown profile: {name}. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]
