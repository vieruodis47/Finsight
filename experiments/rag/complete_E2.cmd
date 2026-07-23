@echo off
rem ============================================================
rem  FinSight — complete experiment E-2 (architecture comparison)
rem  Safe to run repeatedly: finished work is never redone.
rem  Run AFTER 2:00 AM Central (daily Gemini quota reset), once per day.
rem  Requires: Docker Desktop running (script starts the DB containers).
rem ============================================================
setlocal
cd /d "%~dp0..\.."
set RAVENDB_URLS=http://127.0.0.1:8081
set EMBED_CACHE_PATH=%CD%\experiments\rag\results\embed_cache.jsonl
set GEMINI_JUDGE_MODEL=gemma-4-31b-it
set PY=%CD%\.venv\Scripts\python.exe
set LOG=%CD%\experiments\rag\results\e2_completion.log
set EVAL=experiments\rag\eval\questions.v1.jsonl

echo ============ E-2 completion %DATE% %TIME% ============ >> "%LOG%"
echo Starting RavenDB containers (no-op if already running)...
docker start finsight-ravendb-1 raven-proxy >> "%LOG%" 2>&1
timeout /t 15 /nobreak > nul

echo [1/2] Running remaining E-2 runs (resume-safe)...
"%PY%" -u experiments\rag\runner.py --exp E-2 --variants naive,graph,hyde,agentic,modular --eval %EVAL% --repeats 3 >> "%LOG%" 2>&1

echo [2/2] Scoring E-2...
"%PY%" -u experiments\rag\scorer.py --exp E-2 --eval %EVAL% >> "%LOG%" 2>&1

echo ============ finished %DATE% %TIME% ============ >> "%LOG%"
echo.
echo Done. Check experiments\rag\results\E-2\summary.json
echo Full log: %LOG%
if "%~1"=="" pause
