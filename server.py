from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import subprocess
import os
import tempfile
import json
import threading
from pathlib import Path
import sys

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configuration
MOONSEC_PATH = Path("MoonsecDeobfuscator-master")
BUILD_PATH = MOONSEC_PATH / "bin" / "Release" / "net8.0"

def check_dotnet():
    """Check if .NET is available"""
    try:
        result = subprocess.run(["dotnet", "--version"], 
                              capture_output=True, 
                              text=True, 
                              timeout=5)
        return result.returncode == 0
    except:
        return False

def build_moonsec():
    """Build the Moonsec tool"""
    try:
        print("🔨 Building Moonsec Deobfuscator...")
        
        # Clean and build
        result = subprocess.run(
            ["dotnet", "clean", "-c", "Release"],
            cwd=str(MOONSEC_PATH),
            capture_output=True,
            text=True
        )
        
        result = subprocess.run(
            ["dotnet", "build", "-c", "Release"],
            cwd=str(MOONSEC_PATH),
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print("✅ Build successful!")
            return True
        else:
            print(f"❌ Build failed: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ Build error: {e}")
        return False

@app.route('/')
def index():
    """Home page"""
    return jsonify({
        "name": "Moonsec Deobfuscator API",
        "version": "1.0.0",
        "status": "running"
    })

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    dotnet_available = check_dotnet()
    moonsec_exists = MOONSEC_PATH.exists()
    
    return jsonify({
        "status": "ok",
        "dotnet": dotnet_available,
        "moonsec_path": str(MOONSEC_PATH),
        "moonsec_exists": moonsec_exists,
        "timestamp": os.path.getmtime(str(MOONSEC_PATH)) if moonsec_exists else 0
    })

@app.route('/deobfuscate', methods=['POST'])
def deobfuscate():
    """Main deobfuscation endpoint"""
    try:
        # Get request data
        data = request.get_json()
        
        if not data or 'content' not in data:
            return jsonify({
                "success": False,
                "error": "No content provided"
            }), 400
        
        # Validate Moonsec path
        if not MOONSEC_PATH.exists():
            return jsonify({
                "success": False,
                "error": f"MoonsecDeobfuscator not found at: {MOONSEC_PATH}"
            }), 500
        
        # Create temporary files
        with tempfile.NamedTemporaryFile(mode='w', suffix='.lua', delete=False, encoding='utf-8') as f:
            f.write(data['content'])
            input_path = f.name
        
        output_path = input_path + ".output"
        
        try:
            # Determine command
            disassembly = data.get('disassembly', False)
            command = "-dis" if disassembly else "-dev"
            
            # Check if build is needed
            if not BUILD_PATH.exists():
                if not build_moonsec():
                    return jsonify({
                        "success": False,
                        "error": "Failed to build Moonsec tool"
                    }), 500
            
            # Find the executable
            exe_path = None
            possible_paths = [
                BUILD_PATH / "MoonsecDeobfuscator.exe",  # Windows
                BUILD_PATH / "MoonsecDeobfuscator",      # Linux/Mac
                MOONSEC_PATH / "bin" / "Release" / "net8.0" / "MoonsecDeobfuscator.exe",
                MOONSEC_PATH / "bin" / "Release" / "net8.0" / "MoonsecDeobfuscator"
            ]
            
            for path in possible_paths:
                if path.exists():
                    exe_path = path
                    break
            
            if not exe_path:
                # Try dotnet run as fallback
                dll_path = BUILD_PATH / "MoonsecDeobfuscator.dll"
                if dll_path.exists():
                    cmd = ["dotnet", str(dll_path), command, "-i", input_path, "-o", output_path]
                else:
                    return jsonify({
                        "success": False,
                        "error": "Moonsec executable not found. Try building first."
                    }), 500
            else:
                cmd = [str(exe_path), command, "-i", input_path, "-o", output_path]
            
            print(f"Running command: {' '.join(cmd)}")
            
            # Run deobfuscator
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
                encoding='utf-8',
                errors='ignore'
            )
            
            print(f"Return code: {result.returncode}")
            if result.stdout:
                print(f"STDOUT: {result.stdout[:200]}")
            if result.stderr:
                print(f"STDERR: {result.stderr[:200]}")
            
            if result.returncode != 0:
                error_msg = result.stderr.strip() if result.stderr else "Unknown error"
                return jsonify({
                    "success": False,
                    "error": f"Deobfuscation failed: {error_msg}"
                }), 500
            
            # Read output file
            if os.path.exists(output_path):
                with open(output_path, 'r', encoding='utf-8', errors='ignore') as f:
                    output_content = f.read()
                
                # Format output if requested
                if data.get('pretty', True):
                    output_content = format_output(output_content, disassembly)
                
                return jsonify({
                    "success": True,
                    "result": output_content,
                    "format": "disassembly" if disassembly else "bytecode",
                    "original_filename": data.get('filename', 'unknown.lua')
                })
            else:
                return jsonify({
                    "success": False,
                    "error": "Output file was not created"
                }), 500
                
        except subprocess.TimeoutExpired:
            return jsonify({
                "success": False,
                "error": "Process timed out after 30 seconds"
            }), 500
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"Processing error: {str(e)}"
            }), 500
        finally:
            # Cleanup temporary files
            try:
                if os.path.exists(input_path):
                    os.unlink(input_path)
                if os.path.exists(output_path):
                    os.unlink(output_path)
            except:
                pass
                
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Server error: {str(e)}"
        }), 500

def format_output(content, is_disassembly):
    """Format output for better readability"""
    if not content:
        return content
    
    if is_disassembly:
        # Format disassembly
        lines = content.split('\n')
        formatted = []
        for line in lines:
            line = line.rstrip()
            if line:
                formatted.append(line)
        return '\n'.join(formatted)
    else:
        # Format Lua/bytecode
        # Add newlines after semicolons and braces
        formatted = content.replace(';', ';\n')
        formatted = formatted.replace('{', '{\n')
        formatted = formatted.replace('}', '\n}')
        
        # Remove excessive blank lines
        lines = formatted.split('\n')
        lines = [line.rstrip() for line in lines if line.strip()]
        return '\n'.join(lines)

@app.route('/test', methods=['GET'])
def test():
    """Test endpoint with sample Lua code"""
    sample_lua = '''local chars = { "H", "e", "l", "l", "o ", "W", "o", "r", "l", "d", "!" }
local result = ""
for i = 1, #chars do
    result = result .. chars[i]
end
print(result)'''
    
    return jsonify({
        "test": "Moonsec API is working",
        "sample": sample_lua,
        "endpoints": {
            "POST /deobfuscate": "Deobfuscate Lua code",
            "GET /health": "Check system health",
            "GET /test": "This test endpoint"
        }
    })

if __name__ == '__main__':
    print("🚀 Starting Moonsec Deobfuscator Server")
    print("=" * 50)
    
    # Check requirements
    print("🔍 Checking requirements...")
    
    if not check_dotnet():
        print("❌ .NET SDK not found! Please install .NET 8.0+")
        print("   Download: https://dotnet.microsoft.com/download")
        sys.exit(1)
    
    if not MOONSEC_PATH.exists():
        print(f"❌ MoonsecDeobfuscator-master folder not found!")
        print(f"   Expected at: {MOONSEC_PATH.absolute()}")
        print("   Please make sure the folder is in the same directory as server.py")
        sys.exit(1)
    
    print("✅ .NET SDK is available")
    print(f"✅ Moonsec path: {MOONSEC_PATH}")
    
    # Build in background thread
    def background_build():
        build_moonsec()
    
    build_thread = threading.Thread(target=background_build, daemon=True)
    build_thread.start()
    
    print("🔨 Building Moonsec in background...")
    print("🌐 Server starting on http://127.0.0.1:5000")
    print("=" * 50)
    
    # Start the server
    app.run(
        host='127.0.0.1',
        port=5000,
        debug=False,
        threaded=True
    )