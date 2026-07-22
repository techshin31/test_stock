import subprocess
import os
import sys

project_dir = r"c:\dev\project\Service_Stock_Analysis"
dashboard_dir = os.path.join(project_dir, "dashboard")

# Start backend
subprocess.Popen(
    "uv run uvicorn api.main:app --host 0.0.0.0 --port 8000",
    cwd=project_dir,
    shell=True,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
)

# Start frontend
subprocess.Popen(
    "npm run dev",
    cwd=dashboard_dir,
    shell=True,
    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
)

print("Detached processes started successfully.")
