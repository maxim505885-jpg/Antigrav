"""Uvicorn entrypoint: uvicorn scan2bim.main:app --app-dir backend"""
from .api.app import app

__all__ = ["app"]
