# File: api/index.py

import time
import uuid
import os
import re
from pathlib import Path
from typing import List, Dict, Optional, Any
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

# Initialize FastAPI app
app = FastAPI(
    docs_url="/api/vlr/docs",
    redoc_url="/api/vlr/redoc",
    openapi_url="/api/vlr/openapi.json"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
