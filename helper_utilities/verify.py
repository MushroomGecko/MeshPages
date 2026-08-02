"""Verify that the active MeshPages uv profile is installed correctly."""

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version


REQUIRED_PACKAGES = {
    "meshtastic": "meshtastic",
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "jinja2": "jinja2",
    "python-multipart": "multipart",
    "brotli": "brotli",
    "pydantic": "pydantic",
    "pydantic-core": "pydantic_core",
}

PROFILE_PACKAGES = {
    "default": ("minify-html-onepass", "minify_html_onepass"),
    "termux": ("htmlmin4", "htmlmin"),
}


def main() -> int:
    missing = []
    installed_versions = {}

    for package, module in REQUIRED_PACKAGES.items():
        try:
            import_module(module)
            installed_versions[package] = version(package)
        except (ImportError, PackageNotFoundError) as error:
            missing.append(f"{package}: {error}")

    active_profiles = []
    for profile, (package, module) in PROFILE_PACKAGES.items():
        try:
            import_module(module)
            installed_versions[package] = version(package)
            active_profiles.append(profile)
        except (ImportError, PackageNotFoundError):
            continue

    if missing:
        print("MeshPages installation is incomplete:")
        for package in missing:
            print(f"- {package}")
        return 1

    if len(active_profiles) != 1:
        print("MeshPages profile check failed:")
        if not active_profiles:
            print("- No profile-specific minifier is installed.")
        else:
            print(f"- Multiple profiles are installed: {', '.join(active_profiles)}")
        return 1

    print(f"MeshPages installation verified ({active_profiles[0]} profile).")
    for package, installed_version in installed_versions.items():
        print(f"{package}=={installed_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
