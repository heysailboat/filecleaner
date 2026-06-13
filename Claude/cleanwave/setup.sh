#!/bin/bash
set -e

echo "🌊 CleanWave setup"
echo ""

python3 -m pip install --upgrade pip -q
python3 -m pip install -r requirements.txt

mkdir -p ~/.cleanwave

if [ ! -f ~/.cleanwave/config.yaml ]; then
    cp config.yaml ~/.cleanwave/config.yaml
    echo "✓ Config created at ~/.cleanwave/config.yaml"
else
    echo "  Config already exists at ~/.cleanwave/config.yaml"
fi

if [ ! -f .env ]; then
    cp .env.example .env
    echo "✓ Created .env — open it and add your GROQ_API_KEY"
else
    echo "  .env already exists"
fi

echo ""
echo "Done! Next steps:"
echo "  1. Edit .env and add your GROQ_API_KEY (free at console.groq.com)"
echo "  2. Run:  python3 run.py --dry-run"
echo "  3. When happy:  python3 run.py"
