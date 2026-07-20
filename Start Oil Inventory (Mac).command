#!/bin/bash
# Double-clickable launcher for macOS.
# Keep the Terminal window that opens; close it to stop the app.

cd "$(dirname "$0")"

echo "============================================================"
echo "  Oil Godown Inventory"
echo "  Keep this Terminal window open while you use the app."
echo "  To stop the app, press Ctrl+C or close this window."
echo "============================================================"
echo

# Check Python
if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is not installed. Install it from https://www.python.org/downloads"
    echo "then double-click this file again."
    read -r -p "Press Enter to close..."
    exit 1
fi

# Skip Streamlit's first-run email prompt
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
    mkdir -p "$HOME/.streamlit"
    printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

# Install required packages the first time only
if ! python3 -c "import streamlit, pandas, sqlalchemy" 2>/dev/null; then
    echo "First-time setup: installing required packages..."
    python3 -m pip install --upgrade pip
    python3 -m pip install -r requirements.txt
    echo
fi

echo "Starting the app. Your web browser will open in a moment..."
echo
python3 -m streamlit run app.py
