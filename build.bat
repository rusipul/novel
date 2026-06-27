@echo off
echo [1/3] Building app with PyInstaller...
pyinstaller novelpia-downloader.spec --clean

echo [2/3] Copying Playwright Chromium into dist folder...
python -c "import playwright, os, shutil; src=os.path.join(os.path.dirname(playwright.__file__),'driver'); dst=os.path.join('dist','novelpia-downloader','playwright_driver'); shutil.copytree(src,dst,dirs_exist_ok=True)"

echo [3/3] Done.
echo Run: dist\novelpia-downloader\novelpia-downloader.exe
pause
