#!/bin/bash
echo "Setting up CleanWave..."

# Install Python dependencies
pip install -r requirements.txt

# Create config directory
mkdir -p ~/.cleanwave

# Copy default config if not exists
if [ ! -f ~/.cleanwave/config.yaml ]; then
    cp cleanwave_config.yaml ~/.cleanwave/config.yaml
    echo "Created default config at ~/.cleanwave/config.yaml"
fi

# Set up Groq API key (optional)
if [ -z "$GROQ_API_KEY" ]; then
    echo ""
    echo "Optional: Set your Groq API key for AI features"
    echo "Get one at https://console.groq.com"
    echo "Run: export GROQ_API_KEY='your-key-here'"
    echo "Add to ~/.bashrc or ~/.zshrc to make permanent"
fi

echo ""
echo "Setup complete! Run: python cleanwave_main.py --help"