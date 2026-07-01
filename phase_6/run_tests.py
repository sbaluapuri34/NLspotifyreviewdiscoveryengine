import os
import sys
import subprocess
from pathlib import Path

def main():
    print("="*60)
    print("SPOTIFY PRODUCT RESEARCH ENGINE - PHASE 6 VERIFICATION SUITE")
    print("="*60)
    
    project_root = Path(__file__).resolve().parent.parent
    tests_dir = project_root / "backend" / "tests"
    
    # Set PYTHONPATH
    env = os.environ.copy()
    env["PYTHONPATH"] = str(project_root)
    
    # Run pytest
    print(f"Running backend tests from: {tests_dir}")
    print("Executing: pytest backend/tests/")
    print("-"*60)
    
    try:
        # Use sys.executable to run pytest through the active virtual environment
        cmd = [sys.executable, "-m", "pytest", str(tests_dir), "-v"]
        result = subprocess.run(cmd, env=env, check=False)
        
        print("-"*60)
        if result.returncode == 0:
            print("SUCCESS: ALL VERIFICATION TESTS PASSED SUCCESSFULLY!")
            sys.exit(0)
        else:
            print("FAILED: SOME VERIFICATION TESTS FAILED. Please check the output above.")
            sys.exit(result.returncode)
            
    except Exception as e:
        print(f"ERROR: Error running verification suite: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
