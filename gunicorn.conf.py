import os

os.makedirs("var/log", exist_ok=True)
os.makedirs("var/run", exist_ok=True)

# The granularity of Error log outputs
loglevel = "info"

# The number of worker processes for handling requests
workers = 1
worker_class = "gthread"
threads = 4
timeout = 120

# The socket to bind
bind = "0.0.0.0:8085"

# Don't restart workers when code changes
reload = False

# Write access and error info to var/log
accesslog = errorlog = "var/log/dimi-ul.log"

# Redirect stdout/stderr to log file
capture_output = True

# PID file so you can easily fetch process ID
pidfile = "var/run/dimi-ul.pid"

# Daemonize the Gunicorn process (detach & enter background)
daemon = True
