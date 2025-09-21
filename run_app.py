#!/usr/bin/env python3
"""
Simple script to run the app.py file
"""
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import and run the app
if __name__ == "__main__":
    print("Starting AI Friend Application...")
    try:
        import app
        print("App imported successfully!")
    except Exception as e:
        print(f"Error importing app: {e}")
        import traceback
        traceback.print_exc()
