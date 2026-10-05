"""Own and terminate the entire child process group on timeout or cancellation."""
import os
import signal
import subprocess


def stop_child(child):
    if child.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    elif getattr(child, "quantpilot_owns_group", True):
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
    else:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
    child.wait(timeout=10)


def run_bounded(command, *, cwd, env, timeout):
    owns_group = os.name != "nt" and env.get("QUANTPILOT_SUPERVISED") != "1"
    child = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=owns_group)
    child.quantpilot_owns_group = owns_group
    try:
        return child.wait(timeout=timeout)
    except BaseException:
        stop_child(child)
        raise
