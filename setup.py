#!/usr/bin/env python3
"""
Antarā Setup Script
Automates the setup process for local development
"""

import os
import subprocess
import sys
from pathlib import Path

def run_command(command, cwd=None):
    """Run a shell command and return success status"""
    try:
        result = subprocess.run(command, shell=True, cwd=cwd, check=True, 
                              capture_output=True, text=True)
        print(f"✅ {command}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {command}")
        print(f"Error: {e.stderr}")
        return False

def check_requirements():
    """Check if required tools are installed"""
    print("🔍 Checking requirements...")
    
    # Check Python
    try:
        python_version = subprocess.check_output([sys.executable, "--version"], text=True)
        print(f"✅ {python_version.strip()}")
    except:
        print("❌ Python not found")
        return False
    
    # Check Node.js
    try:
        node_version = subprocess.check_output(["node", "--version"], text=True)
        print(f"✅ Node.js {node_version.strip()}")
    except:
        print("❌ Node.js not found. Please install Node.js 16+")
        return False
    
    # Check npm
    try:
        npm_version = subprocess.check_output(["npm", "--version"], text=True)
        print(f"✅ npm {npm_version.strip()}")
    except:
        print("❌ npm not found")
        return False
    
    return True

def setup_backend():
    """Set up the backend environment"""
    print("\n🔧 Setting up backend...")
    
    backend_dir = Path("antara_engine")
    if not backend_dir.exists():
        print("❌ Backend directory not found")
        return False
    
    # Create virtual environment
    if not run_command(f"{sys.executable} -m venv venv", cwd=backend_dir):
        return False
    
    # Determine activation script based on OS
    if os.name == 'nt':  # Windows
        activate_script = "venv\\Scripts\\activate"
        pip_command = "venv\\Scripts\\pip"
    else:  # Unix/Linux/macOS
        activate_script = "source venv/bin/activate"
        pip_command = "venv/bin/pip"
    
    # Install requirements
    if not run_command(f"{pip_command} install -r requirements.txt", cwd=backend_dir):
        return False
    
    # Copy environment file
    env_example = backend_dir / ".env.example"
    env_file = backend_dir / ".env"
    
    if env_example.exists() and not env_file.exists():
        env_example.rename(env_file)
        print("✅ Created .env file from template")
        print("⚠️  Please edit antara_engine/.env and add your GEMINI_API_KEY")
    
    return True

def setup_frontend():
    """Set up the frontend environment"""
    print("\n🎨 Setting up frontend...")
    
    frontend_dir = Path("frontend")
    if not frontend_dir.exists():
        print("❌ Frontend directory not found")
        return False
    
    # Install npm dependencies
    if not run_command("npm install", cwd=frontend_dir):
        return False
    
    # Copy environment file
    env_example = frontend_dir / ".env.example"
    env_file = frontend_dir / ".env"
    
    if env_example.exists() and not env_file.exists():
        env_example.rename(env_file)
        print("✅ Created .env file from template")
    
    return True

def create_start_scripts():
    """Create convenient start scripts"""
    print("\n📝 Creating start scripts...")
    
    # Backend start script
    backend_script = """#!/bin/bash
cd antara_engine
source venv/bin/activate 2>/dev/null || venv\\Scripts\\activate
python main.py
"""
    
    with open("start_backend.sh", "w") as f:
        f.write(backend_script)
    
    # Frontend start script
    frontend_script = """#!/bin/bash
cd frontend
npm run dev
"""
    
    with open("start_frontend.sh", "w") as f:
        f.write(frontend_script)
    
    # Make scripts executable on Unix systems
    if os.name != 'nt':
        os.chmod("start_backend.sh", 0o755)
        os.chmod("start_frontend.sh", 0o755)
    
    print("✅ Created start_backend.sh and start_frontend.sh")

def main():
    """Main setup function"""
    print("🌟 Antarā Setup Script")
    print("=" * 50)
    
    if not check_requirements():
        print("\n❌ Requirements check failed. Please install missing dependencies.")
        sys.exit(1)
    
    if not setup_backend():
        print("\n❌ Backend setup failed.")
        sys.exit(1)
    
    if not setup_frontend():
        print("\n❌ Frontend setup failed.")
        sys.exit(1)
    
    create_start_scripts()
    
    print("\n🎉 Setup completed successfully!")
    print("\n📋 Next steps:")
    print("1. Edit antara_engine/.env and add your GEMINI_API_KEY")
    print("2. Run the backend: ./start_backend.sh (or python antara_engine/main.py)")
    print("3. Run the frontend: ./start_frontend.sh (or cd frontend && npm run dev)")
    print("4. Open http://localhost:3000 in your browser")
    print("\n✨ Your inner world awaits!")

if __name__ == "__main__":
    main()
