@echo off
rem Builds di2swap.dll into launcher\payload with MinGW-w64 GCC (for example w64devkit).
rem gcc.exe must be on PATH, or set CC to its full path before running this.
if "%CC%"=="" set CC=gcc
"%CC%" -O2 -shared -s -static -Wall -Wextra -Wno-cast-function-type -o "%~dp0..\launcher\payload\di2swap.dll" "%~dp0di2swap.c" -lwinmm
if errorlevel 1 exit /b 1
echo built launcher\payload\di2swap.dll
