from packaging.version import Version


def version_less_than(left: str, right: str) -> bool:
    return Version(left.strip()) < Version(right.strip())
