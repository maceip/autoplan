#!/bin/zsh
# Build -> LibreOffice PDF -> PNG. This is the authoritative render.
set -e
cd "$(dirname "$0")"
export FONTCONFIG_FILE=/tmp/fonts.conf
export FONTCONFIG_PATH=/tmp
python3 make.py
rm -rf out/lo out/png
mkdir -p out/lo out/png
~/Applications/LibreOffice.app/Contents/MacOS/soffice --headless --norestore \
  --convert-to pdf --outdir out/lo out/FlashHandoff_v2.pptx >/dev/null 2>&1
pdftoppm -r 96 -png out/lo/FlashHandoff_v2.pdf out/png/s
echo "--- fonts"
pdffonts out/lo/FlashHandoff_v2.pdf | awk 'NR>2{print $1}' | sort -u | head -8
