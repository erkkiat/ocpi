# Troubleshooting

## Table of Contents
1. [Scenarios](#scenarios)
2. [Tools](#tools)
2. [Fluent Bit Commands](#fluent-bit-commands)
3. [Journalctl Commands](#journalctl-commands)
4. [Docker Commands](#docker-commands)
5. [System Monitoring (htop)](#system-monitoring-htop)
6. [Container Memory Usage](#container-memory-usage)
7. [Sentry & OpenSearch Coordination](#sentry--opensearch-coordination)
8. [Relevant Links](#relevant-links)

---

## Scenarios
* Instance out of memory errors
    -  Go to instance
    - Check htop for memory usage
    - Check docker stats for container memory usage
    - If they are recovering memory, monitor over time
    - Check docker logs for OOM errors or in the opensearch dashboard logs for memory errors
    - If persistent OOM errors for specific container, consider restarting the container by docker restart <container_name>
    - if not, try redeploying the same image by doing `sudo bash smappee-deployment/deploy.sh`
    - If issue persists, consider increasing instance memory (Reach out to Heiko/Sander) or optimizing application memory usage
  
* Redeploying
   - ssh into instance
   - Make sure that there are no new images in production
   - Run `sudo bash smappee-deployment/deploy.sh`
   - Run `docker ps` to verify that containers are running
   - Make sure to deploy in all the instances depending on the environment

* Application errors/exceptions
   - Go to OpenSearch Dashboard
   - Go to Discover tab
   - Set time range to last 15 minutes
   - Add filter level: "error/info"
   - Identify error patterns, affected components, trace_id
   - Use trace_id to correlate logs across services
   - Check docker logs for specific containers using trace_id/container name in sentry or docker id in opensearch
   - Check Sentry for related issues using trace_id or error message

## Tools
| Tool | Staging | Production |
|------|---------|------------|
| **OpenSearch Dashboard** | [staging-opensearch](https://dashboards.eu-west-1.aoss.amazonaws.com/_login/?collectionId=yrhk1cu9lpunn04fnl57) | [production-opensearch](https://dashboards.eu-west-1.aoss.amazonaws.com/_login/?collectionId=yrhk1cu9lpunn04fnl57) |
| **Sentry** | [staging-sentry](https://smappee-nv-mj.sentry.io/issues/?environment=staging&project=4509235472498768&statsPeriod=24h) | [production-sentry](https://smappee-nv-mj.sentry.io/issues/?environment=production&project=4509235472498768&statsPeriod=24h) |
| **SolidRoam Portal** | [staging-solidroam](https://solidroam.f3-smappee.net/) | [production-solidroam](https://solidroam.smappee.net/) |



## Fluent Bit Commands

### Service Management
```bash
# Check Fluent Bit service status
sudo systemctl status fluent-bit

# Start Fluent Bit service
sudo systemctl start fluent-bit

# Stop Fluent Bit service
sudo systemctl stop fluent-bit

# Restart Fluent Bit service
sudo systemctl restart fluent-bit

# Reload configuration without restart
sudo systemctl daemon-reload 

```

### Configuration & Testing
```bash
# Validate Fluent Bit configuration
fluent-bit -c /etc/fluent-bit/fluent-bit.conf --dry-run

# Test configuration with verbose output
fluent-bit -c /etc/fluent-bit/fluent-bit.conf -v

# Run Fluent Bit in foreground (debugging)
fluent-bit -c /etc/fluent-bit/fluent-bit.conf

# Check configuration file syntax
cat /etc/fluent-bit/fluent-bit.conf

# Edit configuration
sudo vim /etc/fluent-bit/fluent-bit.conf

# Edit Parsers
sudo vim /etc/fluent-bit/parsers.conf


```

### Log Inspection
```bash
# View Fluent Bit logs (systemd)
sudo journalctl -u fluent-bit -f

# View last 100 lines
sudo journalctl -u fluent-bit -n 100

# View logs since specific time
sudo journalctl -u fluent-bit --since "2025-11-11 10:00:00"

# View logs between time range
sudo journalctl -u fluent-bit --since "2025-11-11 10:00" --until "2025-11-11 11:00"

# View logs with error priority
sudo journalctl -u fluent-bit -p err

# Export logs to file
sudo journalctl -u fluent-bit --since today > fluent-bit-logs.txt

```

### Common Troubleshooting
```bash
# Check if Fluent Bit is running
pgrep -a fluent-bit

# Kill stuck Fluent Bit process
sudo pkill -9 fluent-bit

# Check for configuration errors
fluent-bit -c /etc/fluent-bit/fluent-bit.conf 2>&1 | grep -i error

# Verify output connectivity (OpenSearch)
curl -u user:pass -X GET "https://opensearch-endpoint:9200/_cluster/health"

# Test TCP connection to OpenSearch
nc -zv opensearch-host 9200
```

---

## Journalctl Commands

### Basic Log Viewing
```bash
# Follow all system logs
sudo journalctl -f

# View logs for specific unit
sudo journalctl -u fluent-bit

# View logs for multiple units
sudo journalctl -u fluent-bit -u docker

# View kernel logs
sudo journalctl -k

# View boot messages
sudo journalctl -b
```

### Time-Based Filtering
```bash
# Logs from today
sudo journalctl --since today

# Logs from yesterday
sudo journalctl --since yesterday --until today

# Logs from specific datetime
sudo journalctl --since "2025-11-11 10:00:00"

# Logs from last hour
sudo journalctl --since "1 hour ago"

# Logs from last 30 minutes
sudo journalctl --since "30 min ago"

# Last boot logs
sudo journalctl -b -1

# Current boot logs
sudo journalctl -b 0
```

### Priority & Filtering
```bash
# Show only errors
sudo journalctl -p err

# Show errors and critical
sudo journalctl -p err..crit

# Show warnings and above
sudo journalctl -p warning

# Filter by process name
sudo journalctl _COMM=python

# Filter by PID
sudo journalctl _PID=1234

# Grep through logs
sudo journalctl -u fluent-bit | grep -i error
```

### Output Formatting
```bash
# JSON output
sudo journalctl -u fluent-bit -o json

# JSON pretty print
sudo journalctl -u fluent-bit -o json-pretty

# Short format (traditional syslog)
sudo journalctl -u fluent-bit -o short

# Verbose output (all fields)
sudo journalctl -u fluent-bit -o verbose

# Export format (for archival)
sudo journalctl -u fluent-bit -o export
```

### Log Management
```bash
# Show disk usage
sudo journalctl --disk-usage

# Vacuum logs older than 2 weeks
sudo journalctl --vacuum-time=2weeks

# Vacuum logs larger than 1GB
sudo journalctl --vacuum-size=1G

# Rotate logs
sudo journalctl --rotate

# Verify journal files
sudo journalctl --verify
```

### Advanced Usage
```bash
# Follow logs with 500 lines of history
sudo journalctl -u fluent-bit -n 500 -f

# Follow logs from specific time
sudo journalctl -u fluent-bit --since "10:00" -f

# Show logs reverse chronological
sudo journalctl -u fluent-bit -r

# Show only last 50 lines
sudo journalctl -u fluent-bit -n 50 --no-pager

# Show logs for specific user
sudo journalctl _UID=1000

# Tail multiple services
sudo journalctl -u fluent-bit -u docker -f
```

---

## Docker Commands

### Container Management
```bash
# List running containers
docker ps

# List all containers (including stopped)
docker ps -a

# List containers with size
docker ps -s

# Start container
docker start <container_name>

# Stop container
docker stop <container_name>

# Restart container
docker restart <container_name>

# Remove container
docker rm <container_name>

# Force remove running container
docker rm -f <container_name>


```

### Container Logs
```bash
# View container logs
docker logs <container_name>

# Follow logs
docker logs -f <container_name>

# Show last 100 lines
docker logs --tail 100 <container_name>

# Show logs since timestamp
docker logs --since "2025-11-11T10:00:00" <container_name>

# Show logs with timestamps
docker logs -t <container_name>

# Follow logs from last 50 lines
docker logs --tail 50 -f <container_name>
```

### Container Inspection
```bash
# Inspect container details
docker inspect <container_name>

# Get specific value from inspect
docker inspect -f '{{.State.Status}}' <container_name>

# Get IP address
docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' <container_name>

# Get environment variables
docker inspect -f '{{.Config.Env}}' <container_name>

# Show port mappings
docker port <container_name>

# Show container stats
docker stats <container_name>

# Show stats for all containers
docker stats

# Show resource usage (no stream)
docker stats --no-stream
```

### Container Execution
```bash
# Execute command in running container
docker exec <container_name> <command>

# Interactive shell
docker exec -it <container_name> /bin/bash

# Execute as specific user
docker exec -u root -it <container_name> /bin/bash

# Execute command with environment variable
docker exec -e VAR=value <container_name> <command>

# Copy files from container
docker cp <container_name>:/path/in/container /local/path

# Copy files to container
docker cp /local/path <container_name>:/path/in/container
```

### Docker Commands for Service Management

```bash
# Start all services (if using docker compose file)
docker compose up -d

# Stop all services
docker compose down

# Stop and remove volumes
docker compose down -v

# View logs for all services
docker logs -f django-app &
docker logs -f mqtt-subscriber &
docker logs -f celery-mqtt &
docker logs -f celery-django &

# View logs for specific service
docker logs -f django-app
docker logs -f mqtt-subscriber
docker logs -f celery-mqtt
docker logs -f celery-django

# View logs with timestamps
docker logs -f -t django-app

# Restart specific service
docker restart django-app
docker restart mqtt-subscriber
docker restart celery-mqtt
docker restart celery-django

# Stop specific service
docker stop django-app

# Start specific service
docker start django-app

# View running services
docker ps

# View all services including stopped
docker ps -a

# Execute command in service
docker exec django-app python manage.py shell
docker exec django-app python manage.py createsuperuser
docker exec celery-mqtt celery -A ocpi22.cpo.mqtt.tasks inspect stats

# View service configuration (if using docker compose)
docker compose config

# Validate docker compose.yml
docker compose config --quiet
```

### Service-Specific Commands

```bash
# Django App Operations
docker exec django-app python manage.py check
docker exec django-app python manage.py showmigrations
docker exec django-app python manage.py collectstatic --noinput
docker exec django-app python manage.py shell_plus
docker logs -f django-app --tail=100

# MQTT Subscriber Operations
docker logs -f mqtt-subscriber
docker exec mqtt-subscriber ls -lh /var/log/mqtt/
docker restart mqtt-subscriber

# Celery MQTT Worker Operations
docker logs -f celery-mqtt
docker exec celery-mqtt celery -A ocpi22.cpo.mqtt.tasks inspect active
docker exec celery-mqtt celery -A ocpi22.cpo.mqtt.tasks inspect stats
docker exec celery-mqtt celery -A ocpi22.cpo.mqtt.tasks inspect registered
docker exec celery-mqtt ls -lh /var/log/celery/
docker restart celery-mqtt

# Celery Django Worker Operations
docker logs -f celery-django
docker exec celery-django celery -A ocpi22.tasks inspect active
docker exec celery-django celery -A ocpi22.tasks inspect stats
docker exec celery-django celery -A ocpi22.tasks inspect registered
docker exec celery-django ls -lh /var/log/celery/
docker restart celery-django

# Migrations Service
docker logs django-migrations
```


### Environment File Management

```bash
# Check which env file each service uses
ls -lh *.env
cat django-app.env
cat mqtt-subscriber.env
cat celery-mqtt.env
cat celery-django.env

# Validate environment variables are loaded
docker exec django-app env | grep DJANGO
docker exec mqtt-subscriber env | grep MQTT
docker exec celery-mqtt env | grep CELERY
docker exec celery-django env | grep CELERY
```

### System Cleanup
```bash
# Remove all stopped containers, unused networks, dangling images
docker system prune

# Remove everything including volumes
docker system prune -a --volumes

# Show disk usage
docker system df

# Show detailed disk usage
docker system df -v
```

---

## System Monitoring (htop)

### Basic htop Usage
```bash
# Launch htop
htop

# Launch htop for specific user
htop -u <username>

# Launch htop with specific delay (seconds)
htop -d 10
```

### htop Key Bindings
```
F1 or h    - Help
F2 or S    - Setup (configure htop)
F3 or /    - Search process
F4 or \    - Filter processes
F5 or t    - Tree view
F6 or >    - Sort by column
F7 or ]    - Increase process priority (nice)
F8 or [    - Decrease process priority (nice)
F9 or k    - Kill process
F10 or q   - Quit

Space      - Tag process
U          - Untag all processes
c          - Command line (full path)
u          - Show processes for user
K          - Show kernel threads
H          - Show user threads
I          - Invert sort order
P          - Sort by CPU%
M          - Sort by MEM%
T          - Sort by TIME
```

### Monitoring Tips
```
# Color coding:
- Green bar: Used memory/CPU
- Blue bar: Buffer/cache
- Yellow bar: IRQ time
- Red bar: Kernel time

# CPU bars:
- One bar per CPU core
- Watch for high system (red) vs user (green) time

# Memory:
- Monitor Mem vs Swp usage
- High swap usage indicates memory pressure

# Load average:
- 1, 5, 15 minute averages
- Compare to CPU count (high if > CPU count)
```

### Alternative Monitoring
```bash
# Classic top command
top

# Monitor specific process
top -p <PID>

# Show threads
top -H

# Batch mode (non-interactive)
top -b -n 1 > top-output.txt

# vmstat (virtual memory stats)
vmstat 1 10

# iostat (I/O statistics)
iostat -x 1 10

# Free memory
free -h

# Memory usage with updates
watch -n 1 free -h
```

---

## Container Memory Usage

### Your Docker Containers

Based on your docker compose.yml, here are commands for monitoring your specific containers:

```bash
# Django App Container
docker stats django-app --no-stream
docker stats --format "table {{.Container}}\t{{.MemUsage}}\t{{.MemPerc}}" django-app

# MQTT Subscriber Container
docker stats mqtt-subscriber --no-stream

# Celery Worker - MQTT Queue
docker stats celery-mqtt --no-stream

# Celery Worker - Django Queue
docker stats celery-django --no-stream

# Migrations Container (runs once and exits)
docker ps -a --filter "name=django-migrations" --format "{{.Names}}\t{{.Status}}"
```

### Monitor All Your Application Containers
```bash
# Real-time stats for all running containers
docker stats

# Memory usage table for all your application containers
docker stats --no-stream --format "table {{.Container}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}" \
  django-app \
  mqtt-subscriber \
  celery-mqtt \
  celery-django

# Memory usage sorted by highest
docker stats --no-stream --format "table {{.Container}}\t{{.MemUsage}}\t{{.MemPerc}}" | sort -k3 -rh

# Export stats to file
docker stats --no-stream --format "table {{.Container}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}" > container-stats.txt

# Monitor specific container with human-readable format
docker exec django-app free -h

# Check container resource limits
docker inspect django-app | grep -A 10 "Memory"

# Check all containers including exited ones (for migrations)
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"
```

### Container-Specific Operations

```bash
# Django App
docker logs -f django-app
docker exec -it django-app /bin/bash
docker exec django-app python manage.py check
docker exec django-app python manage.py showmigrations

# MQTT Subscriber
docker logs -f mqtt-subscriber
docker exec -it mqtt-subscriber /bin/bash
# View MQTT logs from volume
docker exec mqtt-subscriber ls -lh /var/log/mqtt/
docker exec mqtt-subscriber tail -f /var/log/mqtt/mqtt-subscriber.log

# Celery Workers
docker logs -f celery-mqtt
docker logs -f celery-django
docker exec -it celery-mqtt /bin/bash
docker exec -it celery-django /bin/bash
# View Celery logs from volume
docker exec celery-mqtt ls -lh /var/log/celery/
docker exec celery-mqtt tail -f /var/log/celery/celery-mqtt.log
docker exec celery-django tail -f /var/log/celery/celery-django.log

# Check Celery worker status
docker exec celery-mqtt celery -A ocpi22.cpo.mqtt.tasks inspect active
docker exec celery-django celery -A ocpi22.tasks inspect active

# Migrations
docker logs django-migrations
```

### Memory Troubleshooting
```bash
# Check container memory limit
docker inspect -f '{{.HostConfig.Memory}}' django-app

# Check if container is OOM killed
docker inspect -f '{{.State.OOMKilled}}' django-app

# View container events for OOM
docker events --filter 'container=django-app' --filter 'event=oom'

# Check logs for memory issues
docker logs django-app | grep -i "memory\|oom"
docker logs celery-mqtt | grep -i "memory\|oom"
docker logs celery-django | grep -i "memory\|oom"
docker logs mqtt-subscriber | grep -i "memory\|oom"

# Monitor memory usage over time (1 sample per second for 60 seconds)
for i in {1..60}; do 
  docker stats --no-stream --format "{{.Container}}\t{{.MemUsage}}" django-app celery-mqtt celery-django mqtt-subscriber; 
  sleep 1; 
done

# Check memory usage for all application containers
docker stats --no-stream --format "table {{.Container}}\t{{.MemUsage}}\t{{.MemPerc}}" \
  django-app mqtt-subscriber celery-mqtt celery-django
```

### Set Memory Limits
```bash
# Update memory limit (2GB) for Django app
docker update --memory=2g django-app

# Update memory + swap limit
docker update --memory=2g --memory-swap=3g django-app

# Set memory limits for Celery workers
docker update --memory=1g celery-mqtt
docker update --memory=1g celery-django

# Set memory limit for MQTT subscriber
docker update --memory=512m mqtt-subscriber

# Check current limits for all containers
docker stats --no-stream --format "table {{.Container}}\t{{.MemUsage}}\t{{.MemPerc}}"
```

### Container Health Checks
```bash
# Check container health status (if healthcheck defined)
docker inspect --format='{{.State.Health.Status}}' django-app

# View health check logs
docker inspect --format='{{range .State.Health.Log}}{{.Output}}{{end}}' django-app

# Check if container is restarting
docker ps -a --filter "name=django-app" --format "{{.Status}}"
docker ps -a --filter "name=celery-mqtt" --format "{{.Status}}"
docker ps -a --filter "name=celery-django" --format "{{.Status}}"
docker ps -a --filter "name=mqtt-subscriber" --format "{{.Status}}"

# Check container restart count
docker inspect --format='{{.RestartCount}}' django-app
docker inspect --format='{{.RestartCount}}' celery-mqtt
docker inspect --format='{{.RestartCount}}' celery-django
docker inspect --format='{{.RestartCount}}' mqtt-subscriber
```

---

## Sentry & OpenSearch Dashboard Coordination

### Overview

**Sentry**: Real-time error tracking and performance monitoring  
**OpenSearch Dashboard**: Log aggregation, search, analytics, and visualization

**Coordination Strategy**: Use Sentry for application errors and performance alerts, OpenSearch Dashboard for comprehensive log analysis and trace correlation using trace_id for errors.

---

#### A. Error Correlation

**Goal**: Find related logs in OpenSearch Dashboard using trace_id/event_id/any fields, time-based and field-based queries


---

#### B. Incident Response Workflow

**When an issue is detected:**

1. **Check OpenSearch Dashboard for error patterns**
   - Navigate to Discover tab
   - Set time range to when issue started
   - Add filter: `level: "error"`
   - Review log volume and patterns

2. **Identify affected components**
   - Check the necessary field in error logs and filter with + lens sign in the row and filter in/out other fields as necessary
   - Identify which services are impacted (django-app, mqtt-subscriber, celery-mqtt, celery-django) or search by docker_id

3. **Find trace_id from error logs**
   - Click on an error log entry
   - Copy the `trace_id` value from the log details
   - Use this to track the full request/message flow

4. **Trace the full flow**
   - Add filter: `trace_id: "your-trace-id"`
   - Sort by @timestamp ascending
   - See how the error propagated through services
   - Identify where the failure originated

5. **Analyze error patterns**
   - Use search to find similar error messages
   - Check frequency of errors over time
   - Identify if it's a spike or ongoing issue

6. **Check Docker container logs**
   ```bash
   # Check logs for the affected time window
   docker logs --since "2025-11-11T10:00:00" --until "2025-11-11T10:30:00" django-app
   docker logs --since "2025-11-11T10:00:00" --until "2025-11-11T10:30:00" mqtt-subscriber
   docker logs --since "2025-11-11T10:00:00" --until "2025-11-11T10:30:00" celery-mqtt
   
   # Or search by trace_id
   docker logs django-app | grep "trace-abc-123"
   ```

7. **Check container resource usage**
   ```bash
   docker stats --no-stream django-app mqtt-subscriber celery-mqtt celery-django
   ```

8. **Review volume logs if needed**
   ```bash
   docker exec mqtt-subscriber tail -200 /var/log/mqtt/mqtt-subscriber.log
   docker exec celery-mqtt tail -200 /var/log/celery/celery-mqtt.log
   ```

9. **Check external dependencies**
   - Verify MQTT broker health
   - Check database connectivity
   - Test external API endpoints
   - Review Redis connection status

10. **Document findings and create action plan**
    - Note the root cause
    - Identify immediate fixes
    - Plan preventive measures

---

#### C. Debugging Workflow

**Scenario**: MQTT message processing failing intermittently

**Step 1: Identify the problem in OpenSearch Dashboard**
- Navigate to OpenSearch Dashboards > Discover
- Add filter: `level: "error"` AND `docker-id: "some-id"`
- Set time range: Last 1 hour
- Look for patterns in error messages
- Note the frequency of errors (spike vs ongoing)

**Step 2: Get trace_id from error logs**
- Click on one of the error log entries
- Locate the `trace_id` field in the log details
- Copy the trace_id value (e.g., "trace-abc-123")

**Step 3: View full trace across all services**
- Clear previous filters
- Add new filter: `trace_id: "trace-abc-123"`
- Sort by @timestamp ascending
- Observe the flow:
  - Where did the request/message originate?
  - Which services processed it?
  - Where did it fail?
  - What was the error message at failure point?

**Step 4: Check Docker container logs with trace_id**
```bash
# Search container logs for the trace_id
docker logs --since "1 hour ago" mqtt-subscriber | grep "trace-abc-123"
docker logs --since "1 hour ago" celery-mqtt | grep "trace-abc-123"
docker logs --since "1 hour ago" celery-django | grep "trace-abc-123"
docker logs --since "1 hour ago" django-app | grep "trace-abc-123"

# Alternative: using docker
docker logs --since 1h mqtt-subscriber | grep "trace-abc-123"
docker logs --since 1h celery-mqtt | grep "trace-abc-123"
```


**Step 6: Analyze error patterns in OpenSearch Dashboard**
- Look for similar error messages (without trace_id filter)
- Search: `message: "MQTTConnectionError"` with time range
- Create visualization: Count of errors over time
- Create visualization: Top error messages
- Identify if it's isolated or systemic

**Step 7: Check Celery task status**
```bash
# Check active tasks
docker exec celery-mqtt celery -A ocpi22.cpo.mqtt.tasks inspect active
docker exec celery-django celery -A ocpi22.tasks inspect active

# Check registered tasks
docker exec celery-mqtt celery -A ocpi22.cpo.mqtt.tasks inspect registered
```

**Step 8: Check container health and resources**
```bash
# Check if containers are healthy
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.RunningFor}}"

# Check resource usage
docker stats --no-stream mqtt-subscriber celery-mqtt celery-django django-app

# Check restart count
docker inspect --format='{{.RestartCount}}' mqtt-subscriber
docker inspect --format='{{.RestartCount}}' celery-mqtt
```

**Step 9: Analyze the timeline in OpenSearch Dashboard**
- Create a timeline visualization
- X-axis: @timestamp (histogram)
- Y-axis: Count of logs
- Split by: `level.keyword` (to see errors vs warnings vs info)
- Identify when the issue started and if it's ongoing

**Step 10: Check external dependencies**
```bash
# Check MQTT broker connectivity (if accessible)
# Check database connectivity
# Check Redis connectivity
# Verify external API endpoints
```

**Step 12: Correlate with system metrics**
```bash
# Check system resources with htop
htop

# Check Fluent Bit status (if logs are being shipped)
sudo systemctl status fluent-bit
sudo journalctl -u fluent-bit -n 50
```

**Step 13: Document findings**
- Note the trace_id(s) affected
- Document the error flow from OpenSearch Dashboard
- Identify root cause
- Create reproduction steps
- Plan the fix

#### Sensitive Data Handling
- Filter sensitive data (passwords, tokens, API keys, credit cards) from logs
- Use `***REDACTED***` placeholder for filtered fields
- Never log raw authentication credentials or PII

#### Performance Monitoring
- Measure and log operation durations (in milliseconds)
- Track database query performance
- Monitor external API response times
- Log resource usage metrics (memory, CPU) during critical operations
- Include trace_id in all performance logs for correlation

---

#### Quick Log Searches in Dashboard
**Find errors in last hour:**
- Filter: `level: "error"`
- Time range: Last 1 hour

**Find logs by trace_id:**
- Filter: `trace_id: "your-trace-id-here"`
- Sort by @timestamp ascending

**Find logs by component:**
- Filter: `component: "mqtt_subscriber"`
- Time range: Custom

**Find specific error message:**
- Search bar: `message: "connection timeout"`
- Add level filter if needed

---

### 4. Troubleshooting Checklist

When investigating an issue:

- [ ] Check OpenSearch Dashboard for error patterns and log volume
- [ ] Identify affected components and time window
- [ ] Extract trace_id from error logs
- [ ] Query OpenSearch for all logs with same trace_id
- [ ] Check OpenSearch for log volume anomalies
- [ ] Review container logs (docker logs) using trace_id
- [ ] Check system resources (htop, docker stats)
- [ ] Verify service health (systemctl status, docker ps)
- [ ] Check network connectivity (ping, curl, nc)
- [ ] Review recent deployments or config changes
- [ ] Check external service status (MQTT broker, external APIs)
- [ ] Analyze full trace flow across all services in OpenSearch Dashboard

# Relevant Links
* [Docker Cheatsheet](https://docs.docker.com/get-started/docker_cheatsheet.pdf)
* [Docker Documentation](https://docs.docker.com/)
* [Fluent Bit - Opensearch](https://docs.fluentbit.io/manual/data-pipeline/outputs/opensearch)