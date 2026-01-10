# GROBID Setup Guide

GROBID (GeneRation Of Bibliographic Data) is used for parsing PDF documents into structured XML/TEI format, extracting sections, titles, authors, and other metadata.

## Quick Start

### Option 1: Using Docker Compose (Recommended)

The easiest way to run GROBID is using the provided Docker Compose file:

```bash
# Start GROBID service
docker-compose -f docker-compose.grobid.yml up -d

# Or use the start script with GROBID
./start.sh --with-grobid
```

This will start GROBID on `http://localhost:8070` by default.

### Option 2: Manual Docker Run

```bash
docker run -d \
  --name grobid \
  -p 8070:8070 \
  -e JAVA_OPTS="-Xmx6g -Xms2g -XX:+UseG1GC -XX:MaxGCPauseMillis=200 -XX:+ExitOnOutOfMemoryError" \
  --memory="8g" \
  --memory-reservation="4g" \
  lfoppiano/grobid:0.8.1
```

### Option 3: Using Environment Variables

If you have GROBID running on a different host/port, you can configure it in `backend/.env`:

```env
# Option 1: Full URL
GROBID_URL=http://your-grobid-host:8070

# Option 2: Host and port separately
GROBID_HOST=localhost
GROBID_PORT=8070
```

## Configuration

The code automatically detects GROBID server in the following order:

1. **GROBID_URL** environment variable (full URL)
2. **GROBID_HOST** and **GROBID_PORT** environment variables
3. Auto-detection by checking common ports (8070, 8080) on localhost

## Health Check

The code includes a health check function that verifies GROBID is running before attempting to parse PDFs. If GROBID is not available, you'll get a helpful error message with instructions.

## Verify GROBID is Running

Check if GROBID is accessible:

```bash
curl http://localhost:8070/api/isalive
```

Should return: `{"status":"alive"}`

## Stopping GROBID

```bash
# Using Docker Compose
docker-compose -f docker-compose.grobid.yml down

# Or using Docker directly
docker stop grobid
docker rm grobid
```

## Troubleshooting

### GROBID not starting

- Ensure Docker is installed and running
- Check if port 8070 is already in use: `lsof -i :8070`
- Check Docker logs: `docker logs grobid`

### Connection errors

- Verify GROBID is running: `curl http://localhost:8070/api/isalive`
- Check firewall settings if using remote GROBID
- Ensure GROBID_URL in `.env` matches your setup
- If GROBID crashes repeatedly, check logs: `docker logs grobid`
- Look for `SIGSEGV` or `OutOfMemoryError` in logs - these indicate memory issues

### Performance

GROBID can be memory-intensive. The Docker setup allocates 6GB of heap memory. For larger PDFs, you may need to increase this:

```yaml
environment:
  - JAVA_OPTS=-Xmx8g -Xms4g  # Increase to 8GB max, 4GB initial
mem_limit: 10g  # Increase Docker memory limit accordingly
```

### JVM Crash (SIGSEGV) Fix

If you see `SIGSEGV` errors in Docker logs (`docker logs grobid`), this is typically due to:

1. **Insufficient memory**: GROBID needs at least 6GB heap for complex PDFs
2. **Memory limits**: Docker may not have enough memory allocated
3. **GC issues**: The G1 garbage collector may need tuning

**Solutions:**
- Ensure Docker Desktop has at least 8GB RAM allocated (Preferences → Resources → Memory)
- The docker-compose file includes memory limits and GC tuning to prevent crashes
- If crashes persist, try switching to a different GC algorithm by modifying `JAVA_OPTS`:
  ```yaml
  - JAVA_OPTS=-Xmx6g -Xms2g -XX:+UseParallelGC -XX:+ExitOnOutOfMemoryError
  ```

## Resources

- [GROBID Documentation](https://grobid.readthedocs.io/)
- [GROBID GitHub](https://github.com/kermitt2/grobid)
- [Docker Hub Image](https://hub.docker.com/r/lfoppiano/grobid)
