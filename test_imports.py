#!/usr/bin/env python3

print("Starting import test...")

try:
    print("Importing standard library modules...")
    import json
    import logging
    import os
    import random
    import re
    import ssl
    import sys
    import threading
    import time
    import uuid
    from collections import defaultdict
    from contextlib import contextmanager
    from datetime import datetime, timedelta, timezone
    from functools import lru_cache
    from queue import Queue
    from typing import Any, Dict, Iterator, List, Optional, Set, Tuple
    print("Standard library imports successful!")
    
    print("Importing bcrypt...")
    import bcrypt
    print("bcrypt import successful!")
    
    print("Importing google.generativeai...")
    import google.generativeai as genai
    print("google.generativeai import successful!")
    
    print("Importing gradio...")
    import gradio as gr
    print("gradio import successful!")
    
    print("Importing nltk...")
    import nltk
    print("nltk import successful!")
    
    print("Importing numpy...")
    import numpy as np
    print("numpy import successful!")
    
    print("Importing requests...")
    import requests
    print("requests import successful!")
    
    print("Importing torch...")
    import torch
    print("torch import successful!")
    
    print("Importing BeautifulSoup...")
    from bs4 import BeautifulSoup
    print("BeautifulSoup import successful!")
    
    print("Importing dotenv...")
    from dotenv import load_dotenv
    print("dotenv import successful!")
    
    print("Importing sentence_transformers...")
    from sentence_transformers import SentenceTransformer
    print("sentence_transformers import successful!")
    
    print("Importing TextBlob...")
    from textblob import TextBlob
    print("TextBlob import successful!")
    
    print("Importing transformers...")
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, pipeline
    print("transformers import successful!")
    
    print("All imports successful!")
    
except Exception as e:
    print(f"Import failed: {e}")
    import traceback
    traceback.print_exc()
